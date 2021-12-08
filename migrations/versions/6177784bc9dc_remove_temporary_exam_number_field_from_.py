"""Remove temporary exam number field from StudentData

Revision ID: 6177784bc9dc
Revises: a1be1524862d
Create Date: 2021-12-08 10:40:03.544372

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '6177784bc9dc'
down_revision = 'a1be1524862d'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_student_data_exam_number_temp', table_name='student_data')
    op.drop_column('student_data', 'exam_number_temp')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('student_data', sa.Column('exam_number_temp', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.create_index('ix_student_data_exam_number_temp', 'student_data', ['exam_number_temp'], unique=False)
    # ### end Alembic commands ###
