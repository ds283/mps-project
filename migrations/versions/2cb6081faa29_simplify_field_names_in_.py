"""Simplify field names in PresentationFeedback

Revision ID: 2cb6081faa29
Revises: da0f101b7826
Create Date: 2018-10-25 00:18:30.205626

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '2cb6081faa29'
down_revision = 'da0f101b7826'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('presentation_feedback', sa.Column('negative', sa.Text(), nullable=True))
    op.add_column('presentation_feedback', sa.Column('positive', sa.Text(), nullable=True))
    op.drop_column('presentation_feedback', 'presentation_positive')
    op.drop_column('presentation_feedback', 'presentation_negative')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('presentation_feedback', sa.Column('presentation_negative', mysql.TEXT(), nullable=True))
    op.add_column('presentation_feedback', sa.Column('presentation_positive', mysql.TEXT(), nullable=True))
    op.drop_column('presentation_feedback', 'positive')
    op.drop_column('presentation_feedback', 'negative')
    # ### end Alembic commands ###
