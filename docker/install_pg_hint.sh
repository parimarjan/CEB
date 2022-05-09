#!/bin/sh

#git clone https://github.com/parimarjan/pg_hint_plan.git
#cd pg_hint_plan
#make
#make install

git clone https://github.com/ossc-db/pg_hint_plan.git
cd pg_hint_plan
git checkout PG12
make
make install
