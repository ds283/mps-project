FROM nginx:1.29.6
LABEL authors="ds283"

# logs expected to be located in /logs
RUN apt-get update && apt-get -y install anacron cron logrotate procps

# copy logrotate configuration file
COPY logrotate.d/nginx /etc/logrotate.d/nginx
COPY cron.daily/logrotate /etc/cron.daily/logrotate
RUN chmod +x /etc/cron.daily/logrotate
COPY logrotate.conf /etc/logrotate.conf

COPY boot.sh /boot.sh
RUN chmod +x /boot.sh

# start nginx and cron (so that logrotate actually gets called)
CMD ["/boot.sh"]
