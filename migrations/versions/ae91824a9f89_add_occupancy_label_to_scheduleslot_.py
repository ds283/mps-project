"""Add occupancy_label to ScheduleSlot model to distinguish multiple slots in the same room

Revision ID: ae91824a9f89
Revises: 136ffcf5ea54
Create Date: 2023-01-04 17:19:25.644998

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ae91824a9f89'
down_revision = '136ffcf5ea54'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('schedule_slots', schema=None) as batch_op:
        batch_op.add_column(sa.Column('occupancy_label', sa.Integer(), nullable=False))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('schedule_slots', schema=None) as batch_op:
        batch_op.drop_column('occupancy_label')

    # ### end Alembic commands ###