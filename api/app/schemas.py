from pydantic import BaseModel, Field
from typing import Literal


# ============================================================
# TEAM SELECTION
# ============================================================

class TeamSelectionRequest(BaseModel):
    team: str = Field(
        min_length=1,
        max_length=32,
        examples=["apple"],
    )


class TeamAvailability(BaseModel):
    name: str
    available: bool


class TeamListResponse(BaseModel):
    game_id: int
    status: str
    teams: list[TeamAvailability]


class TeamSelectionResponse(BaseModel):
    team: str
    token: str
    message: str


# ============================================================
# PUBLIC TEAM INFORMATION
# ============================================================

class PublicTeamResponse(BaseModel):
    team: str
    money: int
    plots: int
    trees: int
    plot_ids: list[int]


# ============================================================
# INVENTORY
# ============================================================

class InventoryResponse(BaseModel):
    money: int
    fruit: int
    seeds: int
    poison: int
    molotov: int


# ============================================================
# PLOTS
# ============================================================

class PlotResponse(BaseModel):
    id: int
    row: int
    column: int
    tree_id: int | None
    connected_plots: list[int]


class PlotListResponse(BaseModel):
    plots: list[PlotResponse]


# ============================================================
# TREES
# ============================================================

class BranchSummaryResponse(BaseModel):
    id: int
    status: str
    fruit: int


class BranchDetailResponse(BaseModel):
    id: int
    tree_id: int
    plot_id: int
    status: str
    fruit: int
    fruit_capacity: int


class TreeSummaryResponse(BaseModel):
    id: int
    plot_id: int
    status: str
    branch_count: int
    fruit: int
    branches: list[BranchSummaryResponse]


class TreeDetailResponse(BaseModel):
    id: int
    plot_id: int
    status: str
    branch_count: int
    fruit: int
    branches: list[BranchSummaryResponse]


class TreeListResponse(BaseModel):
    trees: list[TreeSummaryResponse]


class GameStatusResponse(BaseModel):
    game_id: int
    status: str
    started_at: str | None
    ended_at: str | None
    message: str


class TeamResultResponse(BaseModel):
    place: int
    team: str
    money: int
    fruit: int
    trees: int
    score: int


class GameResultsResponse(BaseModel):
    game_id: int
    winners: list[str]
    tie: bool
    standings: list[TeamResultResponse]


class HarvestRequest(BaseModel):
    amount: int = Field(gt=0)


class HarvestResponse(BaseModel):
    branch_id: int
    harvested: int
    branch_fruit_remaining: int
    inventory_fruit: int


class DeleteBranchResponse(BaseModel):
    branch_id: int
    tree_id: int
    message: str


class DeleteTreeResponse(BaseModel):
    tree_id: int
    plot_id: int
    message: str


class PlantTreeResponse(BaseModel):
    tree_id: int
    plot_id: int
    seeds_spent: int
    seeds_remaining: int
    status: str
    message: str


class MarketItemResponse(BaseModel):
    item: str
    price: int


class MarketResponse(BaseModel):
    items: list[MarketItemResponse]


class MarketPurchaseRequest(BaseModel):
    item: str
    quantity: int = Field(default=1, ge=1)


class MarketPurchaseResponse(BaseModel):
    item: str
    quantity: int
    unit_price: int
    total_cost: int
    money_remaining: int
    message: str


class FruitConversionRequest(BaseModel):
    amount: int = Field(gt=0)
    convert_to: Literal["money", "seeds"]


class FruitConversionResponse(BaseModel):
    fruit_spent: int
    converted_to: str
    amount_received: int

    fruit_remaining: int
    money: int
    seeds: int

    message: str


class PoisonAttackRequest(BaseModel):
    plot_id: int


class PoisonAttackResponse(BaseModel):
    attack_id: int
    target_plot_id: int
    tree_id: int
    poisoned_branch_id: int
    poison_remaining: int
    message: str


class MolotovAttackRequest(BaseModel):
    plot_id: int


class MolotovAttackResponse(BaseModel):
    attack_id: int
    target_plot_id: int
    tree_id: int
    killed_branch_ids: list[int]
    molotov_remaining: int
    tree_status: str
    message: str