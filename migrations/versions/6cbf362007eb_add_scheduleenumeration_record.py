"""Add ScheduleEnumeration record

Revision ID: 6cbf362007eb
Revises: 77ffef80337a
Create Date: 2018-12-09 21:02:25.798516

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6cbf362007eb'
down_revision = '77ffef80337a'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('schedule_enumerations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('category', sa.Integer(), nullable=True),
    sa.Column('enumeration', sa.Integer(), nullable=True),
    sa.Column('key', sa.Integer(), nullable=True),
    sa.Column('schedule_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['schedule_id'], ['scheduling_attempts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('schedule_enumerations')
    # ### end Alembic commands ###
