import datajoint as dj
schema = dj.schema(dj.config.get('database.prefix') +'multitask_network')

@schema
class ReachingDataMark(dj.Manual):
    definition = '''
    monkey: varchar(100)
    condition: tinyint unsigned
    delay_short: smallint unsigned
    muscle_label: tinyint unsigned
    ----- 
    muscle: longblob
    goenvelope: longblob
    times: longblob
    '''