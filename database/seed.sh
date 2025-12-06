#! /bin/bash

echo "------- Dumping Production Schema --------"
pg_dump $PROD_DB_CONNECT_STRING -Fc -t checkins -t challengers -t medals -t challenge_weeks -t challenger_challenges -t challenges --schema-only --no-owner --no-acl -f tables.dump
echo "------------ Creating Tables -------------"
# -h postgres works because the service's name is postgres
# and we're assuming this runs in docker
PGPASSWORD=password pg_restore -d projects -h postgres -U postgres -cCO tables.dump
echo "------- Beginning Database Seeding -------"
echo "---------- Copying Challengers -----------"
psql $PROD_DB_CONNECT_STRING -c "copy (select * from challengers) to stdout" | \
  psql $LOCAL_DB_CONNECT_STRING -c "copy challengers from stdin"
echo "----------- Copying Challenge ------------"
psql $PROD_DB_CONNECT_STRING -c "copy (select * from challenges where id = 23) to stdout" | \
  psql $LOCAL_DB_CONNECT_STRING -c "copy challenges from stdin"
echo "--------- Copying Challenge Weeks --------"
psql $PROD_DB_CONNECT_STRING -c "copy (select * from challenge_weeks where challenge_id = 23) to stdout" | \
  psql $LOCAL_DB_CONNECT_STRING -c "copy challenge_weeks from stdin"
echo "------------ Copying Checkins ------------"
# we have to be extra explicit here because of the two automatic columns
psql $PROD_DB_CONNECT_STRING -c "copy (select name, time, tier, day_of_week, text, challenge_week_id, checkins.id, challenger, tz from checkins join challenge_weeks ON challenge_weeks.id = checkins.challenge_week_id where challenge_weeks.challenge_id = 23) to stdout" | \
  psql $LOCAL_DB_CONNECT_STRING -c "copy checkins from stdin"
# mulligans depends on checkins
echo "------ Copying Challenger Challenges -----"
psql $PROD_DB_CONNECT_STRING -c "copy (select * from challenger_challenges where challenge_id = 23) to stdout" | \
  psql $LOCAL_DB_CONNECT_STRING -c "copy challenger_challenges from stdin"
echo "------------ Copying Medals -------------"
psql $PROD_DB_CONNECT_STRING -c "copy (select * from medals where challenge_id = 23) to stdout" | \
  psql $LOCAL_DB_CONNECT_STRING -c "copy medals from stdin"
echo "----------- Copying Functions -----------"
psql $PROD_DB_CONNECT_STRING -A -t -c "SELECT pg_get_functiondef(oid) || ';' FROM pg_proc where proname like '%score%'" | \
  psql $LOCAL_DB_CONNECT_STRING
echo "-------------- Data Copied --------------"
echo "------- Finished Database Seeding -------"
