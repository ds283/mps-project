"""Add trust_exams field to StudentBatch model

Revision ID: b9304b3b883d
Revises: 6f30081a5119
Create Date: 2019-09-02 23:50:15.723655

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9304b3b883d'
down_revision = '6f30081a5119'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('batch_student', sa.Column('trust_exams', sa.Boolean(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('batch_student', 'trust_exams')
    # ### end Alembic commands ###
