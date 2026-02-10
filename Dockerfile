FROM python:3.14-slim-bookworm

RUN apt-get update && apt-get install -qq -y build-essential gcc gfortran mariadb-client mysqltuner libssl-dev libjpeg-dev zlib1g-dev libglpk-dev libpango1.0-dev glpk-utils coinor-cbc git pkg-config swig wget libcairo2-dev libmagic1 --no-install-recommends

# uid = 500 needed for deployment on Amazon, where ecs-user has uid 500
RUN adduser --disabled-password --shell /bin/bash --gecos '' --uid 1000 mpsproject

RUN mkdir -p /scratch && chown mpsproject:0 /scratch && chmod 774 /scratch
RUN mkdir -p /mpsproject && chown mpsproject:0 /mpsproject && chmod 774 /mpsproject
WORKDIR /mpsproject

# install Python dependencies
COPY --chown=mpsproject:0 --chmod=774 requirements.txt ./

ENV VIRTUAL_ENV=/mpsproject/venv
USER mpsproject
RUN python3 -m venv ${VIRTUAL_ENV}

ENV PATH="$VIRTUAL_ENV/bin:$PATH"
USER mpsproject
RUN pip3 install -U pip setuptools wheel && pip3 install -U -r requirements.txt

# note chmod of 774 is more permissive than we would like (would prefer files not to have x set
# by default, but directories should), but this requires a separate application of chmod which increases
# build time and container size. Currently sticking with this trade-off.
COPY --chown=mpsproject:0 --chmod=774 app ./app/
COPY --chown=mpsproject:0 --chmod=774 migrations ./migrations/
COPY --chown=mpsproject:0 --chmod=774 mpsproject.py serve.py gunicorn_config.py initdb.py celery_node.py migrate.py boot.sh launch_celery.sh launch_beat.sh launch_flower.sh ./

# need destination file for config file local.py to exist, otherwise Docker will create it as a folder
USER mpsproject
RUN touch ./app/instance/local.py

ENV FLASK_ENV production
ENV FLASK_APP mpsproject.py

# web app and flower monitoring tool both run on port 5000
EXPOSE 5000

ENTRYPOINT ["./boot.sh"]
