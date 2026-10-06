from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from sqlalchemy import select, func

from sqlalchemy.exc import IntegrityError

from sqlalchemy.orm import Session

from datetime import datetime, timezone

import random

from app.auth import (

    generate_token,

    get_authenticated_team,

    hash_token,

    require_admin,

)

from app.database import SessionLocal, get_db

from app.game_service import create_game, get_current_game

from app.models import (

    Branch,

    GameStatus,

    GameResult,

    Inventory,

    Plot,
    PlotConnection,

    Team,

    Tree,

    Game,

    TreeStatus,
    Attack,
    AttackStatus,
    AttackType,
    BranchStatus,

)

from app.plot_service import (
    connect_plot_to_neighbors,
    get_connected_plot_ids,
    get_next_plot_position,
)

from app.schemas import (

    BranchDetailResponse,

    BranchSummaryResponse,

    GameResultsResponse,

    GameStatusResponse,

    InventoryResponse,

    PlotListResponse,

    PlotResponse,

    PublicTeamResponse,

    TeamAvailability,

    TeamListResponse,

    TeamResultResponse,

    TeamSelectionRequest,

    TeamSelectionResponse,

    TreeDetailResponse,

    TreeListResponse,

    TreeSummaryResponse,

    DeleteBranchResponse,

    DeleteTreeResponse,

    HarvestRequest,

    HarvestResponse,

    PlantTreeResponse,

    FruitConversionRequest,
    FruitConversionResponse,
    PoisonAttackRequest,
    PoisonAttackResponse,
    MolotovAttackRequest,
    MolotovAttackResponse,
)

from app.events import (

    clear_events,

    schedule_event,

    has_scheduled_event,

)

# ============================================================

# STARTUP

# ============================================================

@asynccontextmanager

async def lifespan(app: FastAPI):

    db = SessionLocal()

    try:

        create_game(db)

    finally:

        db.close()

    yield

# ============================================================

# APPLICATION

# ============================================================


# ============================================================
# MARKET MODELS
# ============================================================

MARKET_PRICES = {
    "plot": 100,
    "poison": 50,
    "molotov": 500,
}


class MarketPurchaseRequest(BaseModel):
    item: str
    quantity: int = Field(default=1, ge=1)


class MarketPurchaseResponse(BaseModel):
    item: str
    quantity: int
    unit_price: int
    total_cost: int
    money_remaining: int
    poison: int
    molotov: int
    plot_ids: list[int]
    message: str


app = FastAPI(

    title="API Trees",

    description="A REST API game for learning HTTP.",

    version="0.2.0",

    lifespan=lifespan,

)

# ============================================================

# GENERAL

# ============================================================

@app.get("/")

def root():

    return {

        "game": "API Trees",

        "message": "Welcome to API Trees.",

        "instructions": "Find an available team to begin.",

        "next": "GET /teams",

    }

@app.post(

    "/admin/start",

    response_model=GameStatusResponse,

)

def start_game(

    _: None = Depends(require_admin),

    db: Session = Depends(get_db),

):

    game = get_current_game(db)

    if game is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="No game exists.",

        )

    if game.status == GameStatus.ACTIVE:

        raise HTTPException(

            status_code=status.HTTP_409_CONFLICT,

            detail="The game has already started.",

        )

    if game.status == GameStatus.FINISHED:

        raise HTTPException(

            status_code=status.HTTP_409_CONFLICT,

            detail="The game has already ended.",

        )

    game.status = GameStatus.ACTIVE

    game.started_at = datetime.now(timezone.utc)

    db.commit()

    db.refresh(game)

    clear_events()

    trees = db.scalars(

    select(Tree)

    .join(Plot)

    .join(Team)

    .where(

        Team.game_id == game.id,

        Team.claimed.is_(True),

    )

    ).all()

    for tree in trees:

        schedule_event(

            "grow_branch",

            30,

            tree_id=tree.id,

        )

    return GameStatusResponse(

        game_id=game.id,

        status=game.status.value,

        started_at=game.started_at.isoformat(),

        ended_at=None,

        message="The game has started.",

    )

@app.post(

    "/admin/end",

    response_model=GameStatusResponse,

)

def end_game(

    _: None = Depends(require_admin),

    db: Session = Depends(get_db),

):

    game = get_current_game(db)

    if game is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="No active game exists.",

        )

    if game.status == GameStatus.LOBBY:

        raise HTTPException(

            status_code=status.HTTP_409_CONFLICT,

            detail="The game has not started.",

        )

    # Only claimed teams participate in results.

    teams = db.scalars(

        select(Team).where(

            Team.game_id == game.id,

            Team.claimed.is_(True),

        )

    ).all()

    if not teams:

        raise HTTPException(

            status_code=status.HTTP_409_CONFLICT,

            detail="Cannot end a game with no claimed teams.",

        )

    results = []

    for team in teams:

        inventory = team.inventory

        tree_count = sum(

            1

            for plot in team.plots

            if plot.tree is not None

        )

        score = (

            inventory.money

            + (inventory.fruit * 10)

            + (tree_count * 100)

        )

        results.append({

            "team": team,

            "money": inventory.money,

            "fruit": inventory.fruit,

            "trees": tree_count,

            "score": score,

        })

    # Score determines ranking.

    results.sort(

        key=lambda result: result["score"],

        reverse=True,

    )

    # Competition ranking:

    #

    # 1000 -> place 1

    # 1000 -> place 1

    #  900 -> place 3

    #  800 -> place 4

    previous_score = None

    current_place = 0

    for index, result in enumerate(

        results,

        start=1,

    ):

        if result["score"] != previous_score:

            current_place = index

        db.add(

            GameResult(

                game_id=game.id,

                team_id=result["team"].id,

                money=result["money"],

                fruit=result["fruit"],

                trees=result["trees"],

                score=result["score"],

                place=current_place,

            )

        )

        previous_score = result["score"]

    game.status = GameStatus.FINISHED

    game.ended_at = datetime.now(timezone.utc)

    db.commit()

    db.refresh(game)

    game.status = GameStatus.FINISHED

    # Remove any scheduled events left over from the finished game.
    clear_events()

    # Immediately create the next lobby so another round can begin
    # without restarting the application or manually resetting data.
    create_game(db)

    return GameStatusResponse(

        game_id=game.id,

        status=game.status.value,

        started_at=game.started_at.isoformat(),

        ended_at=game.ended_at.isoformat(),

        message="The game has ended, final results have been recorded, and the next lobby is ready.",

    )

@app.get(
    "/team/{team_name}",
    response_model=PublicTeamResponse,
    tags=["Teams"],
    summary="Get public team status",
)

def get_team_status(
    team_name: str,
    db: Session = Depends(get_db),
):
    team = db.scalar(
        select(Team).where(
            Team.name == team_name
        )
    )

    if team is None:
        raise HTTPException(
            status_code=404,
            detail="Team not found.",
        )

    inventory = db.scalar(
        select(Inventory).where(
            Inventory.team_id == team.id
        )
    )

    plots = db.scalars(
        select(Plot)
        .where(
            Plot.team_id == team.id
        )
        .order_by(
            Plot.row,
            Plot.column,
        )
    ).all()

    tree_count = db.scalar(
        select(func.count(Tree.id))
        .join(
            Plot,
            Tree.plot_id == Plot.id,
        )
        .where(
            Plot.team_id == team.id,
            Tree.status != TreeStatus.DEAD,
        )
    )

    return PublicTeamResponse(
        team=team.name,
        money=inventory.money,
        plots=len(plots),
        trees=tree_count or 0,
        plot_ids=[
            plot.id
            for plot in plots
        ],
    )


@app.get("/health")

def health():

    return {

        "status": "healthy"

    }

# ============================================================

# TEAMS

# ============================================================

@app.get(

    "/teams",

    response_model=TeamListResponse,

)

def get_teams(

    db: Session = Depends(get_db),

):

    game = get_current_game(db)

    if game is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="No game exists.",

        )

    teams = db.scalars(

        select(Team)

        .where(Team.game_id == game.id)

        .order_by(Team.id)

    ).all()

    return TeamListResponse(

        game_id=game.id,

        status=game.status.value,

        teams=[

            TeamAvailability(

                name=team.name,

                available=not team.claimed,

            )

            for team in teams

        ],

    )

@app.post(

    "/teams/select",

    response_model=TeamSelectionResponse,

    status_code=status.HTTP_201_CREATED,

)

def select_team(

    request: TeamSelectionRequest,

    db: Session = Depends(get_db),

):

    game = get_current_game(db)

    if game is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="No game exists.",

        )

    if game.status != GameStatus.LOBBY:

        raise HTTPException(

            status_code=status.HTTP_409_CONFLICT,

            detail="Teams can only be selected while the game is in the lobby.",

        )

    requested_name = request.team.lower().strip()

    # SELECT ... FOR UPDATE prevents two simultaneous requests

    # from successfully claiming the same team.

    team = db.scalar(

        select(Team)

        .where(

            Team.game_id == game.id,

            Team.name == requested_name,

        )

        .with_for_update()

    )

    if team is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail=f"Team '{requested_name}' does not exist.",

        )

    if team.claimed:

        raise HTTPException(

            status_code=status.HTTP_409_CONFLICT,

            detail=f"Team '{requested_name}' has already been selected.",

        )

    token = generate_token()

    team.claimed = True

    team.token = hash_token(token)

    try:

        db.commit()

    except IntegrityError:

        db.rollback()

        raise HTTPException(

            status_code=status.HTTP_409_CONFLICT,

            detail="Unable to claim team.",

        )

    return TeamSelectionResponse(

        team=team.name,

        token=token,

        message=f"Team {team.name} successfully claimed.",

    )

# ============================================================
# ACTIVE GAME AUTHORIZATION
# ============================================================

def require_active_team(
    team: Team = Depends(get_authenticated_team),
    db: Session = Depends(get_db),
):
    game = db.get(Game, team.game_id)

    if game is None or game.status != GameStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This action is only allowed while the game is active.",
        )

    return team

# ============================================================

# AUTHENTICATION TEST

# ============================================================

@app.get("/me")

def get_me(

    team: Team = Depends(get_authenticated_team),

):

    return {

        "team": team.name,

        "authenticated": True,

    }

@app.get(

    "/me/inventory",

    response_model=InventoryResponse,

)

def get_inventory(

    team: Team = Depends(get_authenticated_team),

):

    inventory = team.inventory

    return InventoryResponse(

        money=inventory.money,

        fruit=inventory.fruit,

        seeds=inventory.seeds,

        poison=inventory.poison,

        molotov=inventory.molotov,

    )

@app.get(

    "/me/plots",

    response_model=PlotListResponse,

)

def get_my_plots(

    team: Team = Depends(get_authenticated_team),

    db: Session = Depends(get_db),

):

    plots = db.scalars(

        select(Plot)

        .where(Plot.team_id == team.id)

        .order_by(Plot.id)

    ).all()

    response = []

    for plot in plots:

        response.append(

            PlotResponse(
                id=plot.id,
                row=plot.row,
                column=plot.column,
                tree_id=(
                    plot.tree.id
                    if plot.tree is not None
                    else None
                ),
                connected_plots=get_connected_plot_ids(
                    db,
                    plot.id,
                ),
            )

        )

    return PlotListResponse(

        plots=response

    )

@app.get(

    "/trees",

    response_model=TreeListResponse,

)

def get_trees(

    team: Team = Depends(get_authenticated_team),

    db: Session = Depends(get_db),

):

    trees = db.scalars(

        select(Tree)

        .join(Plot)

        .where(Plot.team_id == team.id)

        .order_by(Tree.id)

    ).all()

    response = []

    for tree in trees:

        branches = sorted(

            tree.branches,

            key=lambda branch: branch.id,

        )

        total_fruit = sum(

            branch.fruit

            for branch in branches

        )

        response.append(

            TreeSummaryResponse(

                id=tree.id,

                plot_id=tree.plot_id,

                status=tree.status.value,

                branch_count=len(branches),

                fruit=total_fruit,

                branches=[

                    BranchSummaryResponse(

                        id=branch.id,

                        status=branch.status.value,

                        fruit=branch.fruit,

                    )

                    for branch in branches

                ],

            )

        )

    return TreeListResponse(

        trees=response

    )

@app.get(

    "/trees/{tree_id}",

    response_model=TreeDetailResponse,

)

def get_tree(

    tree_id: int,

    team: Team = Depends(get_authenticated_team),

    db: Session = Depends(get_db),

):

    tree = db.scalar(

        select(Tree)

        .join(Plot)

        .where(

            Tree.id == tree_id,

            Plot.team_id == team.id,

        )

    )

    if tree is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="Tree not found.",

        )

    branches = sorted(

        tree.branches,

        key=lambda branch: branch.id,

    )

    return TreeDetailResponse(

        id=tree.id,

        plot_id=tree.plot_id,

        status=tree.status.value,

        branch_count=len(branches),

        fruit=sum(

            branch.fruit

            for branch in branches

        ),

        branches=[

            BranchSummaryResponse(

                id=branch.id,

                status=branch.status.value,

                fruit=branch.fruit,

            )

            for branch in branches

        ],

    )

@app.get(

    "/results",

    response_model=GameResultsResponse,

)

def get_results(

    db: Session = Depends(get_db),

):

    game = db.scalar(

        select(Game)

        .where(Game.status == GameStatus.FINISHED)

        .order_by(Game.id.desc())

    )

    if game is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="No finished game exists.",

        )

    results = db.scalars(

        select(GameResult)

        .where(GameResult.game_id == game.id)

        .order_by(

            GameResult.place,

            GameResult.team_id,

        )

    ).all()

    if not results:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="No results exist for this game.",

        )

    standings = []

    for result in results:

        team = db.get(

            Team,

            result.team_id,

        )

        standings.append(

            TeamResultResponse(

                place=result.place,

                team=team.name,

                money=result.money,

                fruit=result.fruit,

                trees=result.trees,

                score=result.score,

            )

        )

    winners = [

        standing.team

        for standing in standings

        if standing.place == 1

    ]

    return GameResultsResponse(

        game_id=game.id,

        winners=winners,

        tie=len(winners) > 1,

        standings=standings,

    )

@app.get(

    "/branches/{branch_id}",

    response_model=BranchDetailResponse,

)

def get_branch(

    branch_id: int,

    team: Team = Depends(get_authenticated_team),

    db: Session = Depends(get_db),

):

    branch = db.scalar(

        select(Branch)

        .join(Tree)

        .join(Plot)

        .where(

            Branch.id == branch_id,

            Plot.team_id == team.id,

        )

    )

    if branch is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="Branch not found.",

        )

    return BranchDetailResponse(

        id=branch.id,

        tree_id=branch.tree_id,

        plot_id=branch.tree.plot_id,

        status=branch.status.value,

        fruit=branch.fruit,

        fruit_capacity=10,

    )

@app.patch(

    "/branches/{branch_id}",

    response_model=HarvestResponse,

)

def harvest_branch(

    branch_id: int,

    request: HarvestRequest,

    team: Team = Depends(require_active_team),

    db: Session = Depends(get_db),

):

    branch = db.scalar(

        select(Branch)

        .join(Tree)

        .join(Plot)

        .where(

            Branch.id == branch_id,

            Plot.team_id == team.id,

        )

    )

    if branch is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="Branch not found.",

        )
    
    if branch.status != BranchStatus.HEALTHY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Fruit cannot be harvested from a "
                f"{branch.status.value} branch."
            ),
        )

    if branch.tree.status != TreeStatus.HEALTHY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Fruit cannot be harvested while the tree "
                f"is {branch.tree.status.value}."
            ),
        )

    if request.amount > branch.fruit:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail=(

                f"Branch only has {branch.fruit} fruit."

            ),

        )

    inventory = db.scalar(

        select(Inventory)

        .where(Inventory.team_id == team.id)

    )

    if inventory is None:

        raise HTTPException(

            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,

            detail="Team inventory not found.",

        )

    branch.fruit -= request.amount

    inventory.fruit += request.amount

    db.commit()

    db.refresh(branch)

    db.refresh(inventory)

    # Fruit growth stops when a branch reaches 10.

    # If harvesting takes it below 10, make sure growth resumes.

    if (

        branch.fruit < 10

        and not has_scheduled_event(

            "grow_fruit",

            branch_id=branch.id,

        )

    ):

        schedule_event(

            "grow_fruit",

            random.randint(2, 10),

            branch_id=branch.id,

        )

    return HarvestResponse(

        branch_id=branch.id,

        harvested=request.amount,

        branch_fruit_remaining=branch.fruit,

        inventory_fruit=inventory.fruit,

    )

@app.delete(

    "/branches/{branch_id}",

    response_model=DeleteBranchResponse,

)

def delete_branch(

    branch_id: int,

    team: Team = Depends(require_active_team),

    db: Session = Depends(get_db),

):

    branch = db.scalar(

        select(Branch)

        .join(Tree)

        .join(Plot)

        .where(

            Branch.id == branch_id,

            Plot.team_id == team.id,

        )

    )

    if branch is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="Branch not found.",

        )

    tree_id = branch.tree_id

    db.delete(branch)

    db.commit()

    # Deleted branches eventually regrow.

    if not has_scheduled_event(

        "grow_branch",

        tree_id=tree_id,

    ):

        schedule_event(

            "grow_branch",

            30,

            tree_id=tree_id,

        )

    return DeleteBranchResponse(

        branch_id=branch_id,

        tree_id=tree_id,

        message="Branch deleted. A replacement can grow in 30 seconds.",

    )

@app.delete(

    "/trees/{tree_id}",

    response_model=DeleteTreeResponse,

)

def delete_tree(

    tree_id: int,

    team: Team = Depends(require_active_team),

    db: Session = Depends(get_db),

):

    tree = db.scalar(

        select(Tree)

        .join(Plot)

        .where(

            Tree.id == tree_id,

            Plot.team_id == team.id,

        )

    )

    if tree is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="Tree not found.",

        )

    plot_id = tree.plot_id

    db.delete(tree)

    db.commit()

    return DeleteTreeResponse(

        tree_id=tree_id,

        plot_id=plot_id,

        message="Tree deleted.",

    )

@app.put(

    "/plots/{plot_id}/tree",

    response_model=PlantTreeResponse,

)

def plant_tree(

    plot_id: int,

    team: Team = Depends(require_active_team),

    db: Session = Depends(get_db),

):
    # Find the plot and make sure this team owns it.

    plot = db.scalar(

        select(Plot)

        .where(

            Plot.id == plot_id,

            Plot.team_id == team.id,

        )

    )

    if plot is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="Plot not found.",

        )

    # A plot can only contain one tree.

    existing_tree = db.scalar(

        select(Tree)

        .where(Tree.plot_id == plot.id)

    )

    if existing_tree is not None:

        raise HTTPException(

            status_code=status.HTTP_409_CONFLICT,

            detail="This plot already has a tree.",

        )

    # Get the team's inventory.

    inventory = db.scalar(

        select(Inventory)

        .where(Inventory.team_id == team.id)

    )

    if inventory is None:

        raise HTTPException(

            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,

            detail="Team inventory not found.",

        )

    # Trees cost 3 seeds.

    if inventory.seeds < 3:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail="Not enough seeds. Planting a tree requires 3 seeds.",

        )

    # Spend the seeds.

    inventory.seeds -= 3

    # Create the new tree.

    tree = Tree(

        plot_id=plot.id,

        status=TreeStatus.HEALTHY,

    )

    db.add(tree)

    # Flush first so the tree gets an ID before the transaction commits.

    db.flush()

    tree_id = tree.id

    # Commit the tree and inventory changes together.

    db.commit()

    db.refresh(tree)

    db.refresh(inventory)

    # The new tree gets its first branch after 30 seconds.

    schedule_event(

        "grow_branch",

        30,

        tree_id=tree_id,

    )

    return PlantTreeResponse(

        tree_id=tree.id,

        plot_id=plot.id,

        seeds_spent=3,

        seeds_remaining=inventory.seeds,

        status=tree.status.value,

        message="Tree planted successfully.",

    )

# ============================================================
# MARKET API
# ============================================================

@app.get("/market")
def get_market():
    return {
        "items": [
            {"item": "plot", "price": MARKET_PRICES["plot"]},
            {"item": "poison", "price": MARKET_PRICES["poison"]},
            {"item": "molotov", "price": MARKET_PRICES["molotov"]},
        ]
    }


@app.post(
    "/market/buy",
    response_model=MarketPurchaseResponse,
)
def buy_market_item(
    request: MarketPurchaseRequest,
    team: Team = Depends(require_active_team),
    db: Session = Depends(get_db),
):
    item = request.item.lower().strip()

    if item not in MARKET_PRICES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid market item. Valid items are: plot, poison, molotov.",
        )

    inventory = db.scalar(
        select(Inventory)
        .where(Inventory.team_id == team.id)
        .with_for_update()
    )

    if inventory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Team inventory not found.",
        )

    unit_price = MARKET_PRICES[item]
    total_cost = unit_price * request.quantity

    if inventory.money < total_cost:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Not enough money. Purchase costs ${total_cost}, "
                f"but the team only has ${inventory.money}."
            ),
        )

    created_plot_ids = []

    if item == "poison":
        inventory.poison += request.quantity

    elif item == "molotov":
        inventory.molotov += request.quantity

    elif item == "plot":
        # A newly purchased plot must attach to the team's existing land.
        # For multiple plots bought in one request, each new plot extends
        # the chain from the previously created/owned plot.
        existing_plot_ids = list(
            db.scalars(
                select(Plot.id)
                .where(Plot.team_id == team.id)
                .order_by(
                    Plot.row,
                    Plot.column,
                )
            ).all()
        )

        if not existing_plot_ids:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Team has no existing plot to connect the purchased plot to."
                ),
            )

        row, column = get_next_plot_position(
            db,
            team.id,
        )

        plot = Plot(
            team_id=team.id,
            row=row,
            column=column,
        )

        db.add(plot)
        db.flush()

        connect_plot_to_neighbors(
            db,
            plot,
        )

        created_plot_ids.append(
            plot.id
        )

    inventory.money -= total_cost

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(inventory)

    return MarketPurchaseResponse(
        item=item,
        quantity=request.quantity,
        unit_price=unit_price,
        total_cost=total_cost,
        money_remaining=inventory.money,
        poison=inventory.poison,
        molotov=inventory.molotov,
        plot_ids=created_plot_ids,
        message=(
            f"Purchased {request.quantity} "
            f"{item}{'s' if request.quantity != 1 else ''}."
        ),
    )


@app.patch(
    "/inventory/fruit",
    response_model=FruitConversionResponse,
)
def convert_fruit(
    request: FruitConversionRequest,
    team: Team = Depends(require_active_team),
    db: Session = Depends(get_db),
):
    inventory = db.scalar(
        select(Inventory)
        .where(Inventory.team_id == team.id)
        .with_for_update()
    )

    if inventory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Team inventory not found.",
        )

    if inventory.fruit < request.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Not enough fruit. "
                f"Requested {request.amount}, "
                f"but only {inventory.fruit} available."
            ),
        )

    if request.convert_to == "money":
        amount_received = request.amount * 10
        inventory.money += amount_received

    elif request.convert_to == "seeds":
        amount_received = request.amount * 5
        inventory.seeds += amount_received

    inventory.fruit -= request.amount

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(inventory)

    return FruitConversionResponse(
        fruit_spent=request.amount,
        converted_to=request.convert_to,
        amount_received=amount_received,
        fruit_remaining=inventory.fruit,
        money=inventory.money,
        seeds=inventory.seeds,
        message=(
            f"Converted {request.amount} fruit "
            f"into {amount_received} {request.convert_to}."
        ),
    )


@app.post(
    "/attacks/poison",
    response_model=PoisonAttackResponse,
)
def use_poison(
    request: PoisonAttackRequest,
    team: Team = Depends(require_active_team),
    db: Session = Depends(get_db),
):
    inventory = db.scalar(
        select(Inventory)
        .where(Inventory.team_id == team.id)
        .with_for_update()
    )

    if inventory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Team inventory not found.",
        )

    if inventory.poison < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You do not have any poison.",
        )

    # Target may belong to ANY team, including the attacker.
    plot = db.get(
        Plot,
        request.plot_id,
    )

    if plot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plot not found.",
        )

    tree = plot.tree

    if tree is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="There is no tree on this plot.",
        )

    if tree.status == TreeStatus.DEAD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The tree is already dead.",
        )

    healthy_branches = [
        branch
        for branch in tree.branches
        if branch.status == BranchStatus.HEALTHY
    ]

    if not healthy_branches:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This tree has no healthy branches to poison.",
        )

    branch = random.choice(
        healthy_branches
    )

    branch.status = BranchStatus.POISONED

    # Poison destroys all fruit currently on this branch.
    branch.fruit = 0

    inventory.poison -= 1

    attack = Attack(
        attacker_team_id=team.id,
        target_plot_id=plot.id,
        attack_type=AttackType.POISON,
        status=AttackStatus.ACTIVE,
    )

    db.add(attack)
    db.flush()

    attack_id = attack.id

    db.commit()

    # Spread to another branch in 10 seconds.
    schedule_event(
        "spread_poison",
        10,
        attack_id=attack_id,
        tree_id=tree.id,
    )

    return PoisonAttackResponse(
        attack_id=attack_id,
        target_plot_id=plot.id,
        tree_id=tree.id,
        poisoned_branch_id=branch.id,
        poison_remaining=inventory.poison,
        message=(
            f"Poison used on plot {plot.id}. "
            f"Branch {branch.id} was poisoned."
        ),
    )


@app.post(
    "/attacks/molotov",
    response_model=MolotovAttackResponse,
)
def use_molotov(
    request: MolotovAttackRequest,
    team: Team = Depends(require_active_team),
    db: Session = Depends(get_db),
):
    inventory = db.scalar(
        select(Inventory)
        .where(Inventory.team_id == team.id)
        .with_for_update()
    )

    if inventory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Team inventory not found.",
        )

    if inventory.molotov < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You do not have any molotovs.",
        )

    # Molotovs may target any plot, including your own.
    plot = db.get(
        Plot,
        request.plot_id,
    )

    if plot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plot not found.",
        )

    tree = plot.tree

    if tree is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="There is no tree on this plot.",
        )

    if tree.status == TreeStatus.DEAD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The tree is already dead.",
        )

    if tree.status == TreeStatus.BURNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The tree is already burning.",
        )

    living_branches = [
        branch
        for branch in tree.branches
        if branch.status != BranchStatus.DEAD
    ]

    if not living_branches:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The tree has no living branches.",
        )

    inventory.molotov -= 1

    tree.status = TreeStatus.BURNING

    # Immediately kill up to two branches.
    initial_targets = random.sample(
        living_branches,
        min(2, len(living_branches)),
    )

    killed_branch_ids = []

    for branch in initial_targets:
        branch.status = BranchStatus.DEAD
        branch.fruit = 0
        killed_branch_ids.append(branch.id)

    attack = Attack(
        attacker_team_id=team.id,
        target_plot_id=plot.id,
        attack_type=AttackType.MOLOTOV,
        status=AttackStatus.ACTIVE,
    )

    db.add(attack)
    db.flush()

    attack_id = attack.id

    # If those initial hits killed every branch,
    # the tree dies immediately.
    remaining_branches = [
        branch
        for branch in tree.branches
        if branch.status != BranchStatus.DEAD
    ]

    if not remaining_branches:
        tree.status = TreeStatus.DEAD
        attack.status = AttackStatus.FINISHED
        attack.finished_at = datetime.now(
            timezone.utc
        )

    db.commit()

    # Otherwise let the worker continue the fire.
    if tree.status == TreeStatus.BURNING:
        schedule_event(
            "spread_fire",
            10,
            attack_id=attack_id,
            tree_id=tree.id,
        )

    return MolotovAttackResponse(
        attack_id=attack_id,
        target_plot_id=plot.id,
        tree_id=tree.id,
        killed_branch_ids=killed_branch_ids,
        molotov_remaining=inventory.molotov,
        tree_status=tree.status.value,
        message=(
            f"Molotov thrown at plot {plot.id}. "
            f"Tree {tree.id} is burning."
        ),
    )
