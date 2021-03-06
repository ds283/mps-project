"""Begin to add hinting data to SelectionRecord

Revision ID: c63a00b3548f
Revises: 6f5e8ab8fede
Create Date: 2018-08-30 16:33:51.647509

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c63a00b3548f'
down_revision = '6f5e8ab8fede'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('selections', sa.Column('converted_from_bookmark', sa.Boolean(), nullable=True))
    op.add_column('selections', sa.Column('hint', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('selections', 'hint')
    op.drop_column('selections', 'converted_from_bookmark')
    # ### end Alembic commands ###
