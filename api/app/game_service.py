from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Game,
    GameStatus,
    Inventory,
    Plot,
    PlotConnection,
    Team,
    Tree,
)


TEAM_NAMES = [
    "apple",
    "orange",
    "cherry",
    "plum",
    "pear",
    "chestnut",
    "walnut",
    "peach",
]


def get_current_game(db: Session) -> Game | None:
    return db.scalar(
        select(Game)
        .where(Game.status.in_([
            GameStatus.LOBBY,
            GameStatus.ACTIVE,
        ]))
        .order_by(Game.id.desc())
    )


def create_game(db: Session) -> Game:
    existing_game = get_current_game(db)

    if existing_game:
        return existing_game

    game = Game(status=GameStatus.LOBBY)

    db.add(game)
    db.flush()

    for team_name in TEAM_NAMES:
        team = Team(
            game_id=game.id,
            name=team_name,
            claimed=False,
        )

        db.add(team)
        db.flush()

        inventory = Inventory(
            team_id=team.id,
            money=300,
            seeds=3,
            fruit=0,
            poison=0,
            molotov=0,
        )

        db.add(inventory)

        # Every team starts with three plots.
        plot_1 = Plot(team_id=team.id, row=0, column=0)
        plot_2 = Plot(team_id=team.id, row=0, column=1)
        plot_3 = Plot(team_id=team.id, row=0, column=2)

        db.add_all([
            plot_1,
            plot_2,
            plot_3,
        ])

        db.flush()

        # Starting topology:
        #
        # plot_1 ---- plot_2 ---- plot_3

        db.add(
            PlotConnection(
                plot_a_id=plot_1.id,
                plot_b_id=plot_2.id,
            )
        )

        db.add(
            PlotConnection(
                plot_a_id=plot_2.id,
                plot_b_id=plot_3.id,
            )
        
        )
        # Every team begins with one tree.
        # Put it on the center plot.
        tree = Tree(
            plot_id=plot_2.id,
        )

        db.add(tree)

    db.commit()
    db.refresh(game)

    return game