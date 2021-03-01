%{
# Datajoint table for Mark's reaching data
# add primary key here
monkey: varchar(100)
condition: tinyint unsigned
delay_short: smallint unsigned
muscle_label: tinyint unsigned
----- 
muscle: longblob
reach_angle = 0 : smallint unsigned
reach_distance = 0 : smallint unsigned
reach_speed = 0: smallint unsigned
goenvelope: longblob
times: longblob
# add additional attributes
%}

classdef ReachingDataMark < dj.Manual
end