"""add plot grid positions

Revision ID: a7c070e0889d
Revises: f37b715409df
Create Date: 2026-10-05 00:10:57.317966

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7c070e0889d"
down_revision: Union[str, Sequence[str], None] = "f37b715409df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------
    # 1. Add the grid columns as nullable first.
    #
    # Existing plots do not have coordinates yet, so making
    # these NOT NULL immediately would fail.
    # ---------------------------------------------------------

    op.add_column(
        "plots",
        sa.Column(
            "row",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "plots",
        sa.Column(
            "column",
            sa.Integer(),
            nullable=True,
        ),
    )

    # ---------------------------------------------------------
    # 2. Assign existing plots positions.
    #
    # Each team gets its own independent grid:
    #
    # 0,0   0,1   0,2   0,3
    # 1,0   1,1   1,2   1,3
    # 2,0   2,1   2,2   2,3
    #
    # ROW_NUMBER() restarts for each team because we
    # PARTITION BY team_id.
    # ---------------------------------------------------------

    op.execute(
        """
        WITH numbered_plots AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY team_id
                    ORDER BY id
                ) - 1 AS position
            FROM plots
        )
        UPDATE plots
        SET
            "row" = numbered_plots.position / 4,
            "column" = numbered_plots.position % 4
        FROM numbered_plots
        WHERE plots.id = numbered_plots.id
        """
    )

    # ---------------------------------------------------------
    # 3. Now that every existing plot has coordinates,
    # make both columns required.
    # ---------------------------------------------------------

    op.alter_column(
        "plots",
        "row",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.alter_column(
        "plots",
        "column",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # ---------------------------------------------------------
    # 4. Prevent a team from owning two plots in the same
    # grid position.
    # ---------------------------------------------------------

    op.create_unique_constraint(
        "uq_team_plot_position",
        "plots",
        [
            "team_id",
            "row",
            "column",
        ],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_team_plot_position",
        "plots",
        type_="unique",
    )

    op.drop_column(
        "plots",
        "column",
    )

    op.drop_column(
        "plots",
        "row",
    )