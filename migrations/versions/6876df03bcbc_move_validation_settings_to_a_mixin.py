"""Move validation settings to a mixin

Revision ID: 6876df03bcbc
Revises: e54f1756f391
Create Date: 2019-02-26 13:32:36.346141

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '6876df03bcbc'
down_revision = 'e54f1756f391'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('student_data', sa.Column('workflow_state', sa.Integer(), nullable=True))
    op.drop_column('student_data', 'validation_state')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('student_data', sa.Column('validation_state', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.drop_column('student_data', 'workflow_state')
    # ### end Alembic commands ###