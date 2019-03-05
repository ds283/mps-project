"""Add LastViewingTime model; add feedback push fields to SubmissionRecord

Revision ID: 79503e42e0f7
Revises: 1cb478a1c5e5
Create Date: 2019-02-27 13:44:00.976950

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '79503e42e0f7'
down_revision = '1cb478a1c5e5'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('last_view_projects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('last_viewed', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_last_view_projects_last_viewed'), 'last_view_projects', ['last_viewed'], unique=False)
    op.create_index(op.f('ix_description_comments_creation_timestamp'), 'description_comments', ['creation_timestamp'], unique=False)
    op.add_column('submission_records', sa.Column('feedback_push_id', sa.Integer(), nullable=True))
    op.add_column('submission_records', sa.Column('feedback_push_timestamp', sa.DateTime(), nullable=True))
    op.add_column('submission_records', sa.Column('feedback_sent', sa.Boolean(), nullable=True))
    op.create_foreign_key(None, 'submission_records', 'users', ['feedback_push_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'submission_records', type_='foreignkey')
    op.drop_column('submission_records', 'feedback_sent')
    op.drop_column('submission_records', 'feedback_push_timestamp')
    op.drop_column('submission_records', 'feedback_push_id')
    op.drop_index(op.f('ix_description_comments_creation_timestamp'), table_name='description_comments')
    op.drop_index(op.f('ix_last_view_projects_last_viewed'), table_name='last_view_projects')
    op.drop_table('last_view_projects')
    # ### end Alembic commands ###