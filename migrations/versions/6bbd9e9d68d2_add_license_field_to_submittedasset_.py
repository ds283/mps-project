"""Add license field to SubmittedAsset model; add DownloadRecord model

Revision ID: 6bbd9e9d68d2
Revises: af1f7da8b1e8
Create Date: 2020-01-02 21:27:12.542709

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6bbd9e9d68d2'
down_revision = 'af1f7da8b1e8'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('submitted_downloads',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=True),
    sa.Column('downloader_id', sa.Integer(), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['asset_id'], ['submitted_assets.id'], ),
    sa.ForeignKeyConstraint(['downloader_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_submitted_downloads_timestamp'), 'submitted_downloads', ['timestamp'], unique=False)
    op.add_column('submitted_assets', sa.Column('license_id', sa.Integer(), nullable=True))
    op.create_foreign_key(None, 'submitted_assets', 'asset_licenses', ['license_id'], ['id'])
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'submitted_assets', type_='foreignkey')
    op.drop_column('submitted_assets', 'license_id')
    op.drop_index(op.f('ix_submitted_downloads_timestamp'), table_name='submitted_downloads')
    op.drop_table('submitted_downloads')
    # ### end Alembic commands ###
