"""Add registration_number property to StudentData

Revision ID: 2720bc86be69
Revises: 0bdfa1ff3f9f
Create Date: 2020-09-24 23:20:43.711814

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2720bc86be69'
down_revision = '0bdfa1ff3f9f'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('batch_student_items', sa.Column('registration_number', sa.Integer(), nullable=True))
    op.create_unique_constraint(None, 'batch_student_items', ['registration_number'])
    op.add_column('student_data', sa.Column('registration_number', sa.Integer(), nullable=True))
    op.create_unique_constraint(None, 'student_data', ['registration_number'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'student_data', type_='unique')
    op.drop_column('student_data', 'registration_number')
    op.drop_constraint(None, 'batch_student_items', type_='unique')
    op.drop_column('batch_student_items', 'registration_number')
    # ### end Alembic commands ###
