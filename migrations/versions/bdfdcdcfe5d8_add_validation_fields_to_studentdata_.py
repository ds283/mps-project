"""Add validation fields to StudentData record

Revision ID: bdfdcdcfe5d8
Revises: 342bf3bbb8ac
Create Date: 2019-01-16 16:38:52.657361

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bdfdcdcfe5d8'
down_revision = '342bf3bbb8ac'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('student_data', sa.Column('validated_timestamp', sa.DateTime(), nullable=True))
    op.add_column('student_data', sa.Column('validation_state', sa.Integer(), nullable=True))
    op.add_column('student_data', sa.Column('validator_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'student_data', 'users', ['validator_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'student_data', type_='foreignkey')
    op.drop_column('student_data', 'validator_id')
    op.drop_column('student_data', 'validation_state')
    op.drop_column('student_data', 'validated_timestamp')
    # ### end Alembic commands ###