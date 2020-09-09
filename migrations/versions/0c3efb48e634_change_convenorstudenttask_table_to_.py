"""Change ConvenorStudentTask table to allow single table polymorphism

Revision ID: 0c3efb48e634
Revises: a7ca04b7860d
Create Date: 2020-09-01 21:08:26.856386

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0c3efb48e634'
down_revision = 'a7ca04b7860d'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('convenor_tasks', sa.Column('type', sa.Integer(), nullable=False))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('convenor_tasks', 'type')
    # ### end Alembic commands ###
