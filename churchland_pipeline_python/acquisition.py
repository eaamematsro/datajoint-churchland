import datajoint as dj
import re, os
from . import lab, equipment, reference
from brpylib import NsxFile, brpylib_ver
from collections import ChainMap
from typing import List

schema = dj.schema('churchland_common_acquisition') 
#schema = dj.schema(dj.config.get('database.prefix','') + 'churchland_common_acquisition')

# -------------------------------------------------------------------------------------------------------------------------------
# LEVEL 0
# -------------------------------------------------------------------------------------------------------------------------------

@schema
class Task(dj.Lookup):
    definition = """
    # Experimental tasks
    task:         varchar(32) # unique task name
    task_version: varchar(8)  # task version
    ---
    -> equipment.Hardware.proj(task_controller_hardware = 'hardware')
    -> equipment.Software.proj(task_controller_software = 'software', task_controller_software_version = 'software_version')
    -> equipment.Software.proj(graphics = 'software', graphics_version = 'software_version')
    task_description: varchar(255) # additional task details
    """
    
    contents = [
        ['pacman',     '1.0', 'Speedgoat', 'Simulink', '', 'Psychtoolbox', '3.0', '1-dimensional force tracking'],
        ['two target', '1.0', 'Speedgoat', 'Simulink', '', 'Unity 3D',     '',    ''],
        ['reaching',   '1.0', 'Speedgoat', 'Simulink', '', 'Psychtoolbox', '3.0', ''],
    ]

# -------------------------------------------------------------------------------------------------------------------------------
# LEVEL 1
# -------------------------------------------------------------------------------------------------------------------------------

@schema
class Session(dj.Manual):
    definition = """
    # Recording session
    session_date: date # session date
    -> lab.Monkey
    ---
    -> lab.Rig
    -> Task
    session_problem = 0: bool
    session_problem_description = null: varchar(255) # (e.g. corrupted data)
    """

    class Hardware(dj.Part):
        definition = """
        # Hardware used for the recording session
        -> master
        -> equipment.Hardware
        """

    class User(dj.Part):
        definition = """
        -> master
        -> lab.User
        """

    class Notes(dj.Part):
        definition = """
        # Session note
        -> master
        session_notes_id: tinyint unsigned # note ID
        ---
        session_notes: varchar(4095) # note text
        """
        
        def printnotes(self, session, notes_id=0):
            """
            Fetch and print notes
            """
            
            print((self & {'session_date': session, 'session_notes_id': notes_id}).fetch1('session_notes'))
        
    @classmethod
    def getrawpath(self, monkey, rig, task):
        """
        Get path to raw data
        """

        local_path = (reference.EngramPath & {'engram_tier': 'locker'}).getlocalpath()
        raw_path_parts = [rig, task.lower()+'-task', monkey.lower(), 'raw', '']
        return local_path + os.path.sep.join(raw_path_parts)

    @classmethod
    def populate(self,
        monkey: lab.Monkey, 
        rig: lab.Rig, 
        task: Task,
        dates: List[str]=[],
        neural_signal_processor: equipment.Hardware=(equipment.Hardware & {'hardware':'Cerebus'})):

        # check inputs
        for table in [monkey, rig, task]:
            assert len(table) == 1, 'Limit table to one entry:\n\n{}'.format(table)

        assert isinstance(monkey, lab.Monkey), 'Unrecognized monkey table'
        assert isinstance(rig,    lab.Rig),    'Unrecognized rig table'
        assert isinstance(task,   Task),       'Unrecognized task table'
        assert neural_signal_processor.fetch1('hardware_category') == 'neural signal processor', \
            'Expected neural signal processor table entry. Got:\n\n{}'.format(neural_signal_processor)

        # fetch input keys
        monkey_key = monkey.fetch1('KEY')
        rig_key = rig.fetch1('KEY')
        task_key = task.fetch1('KEY')
        nsp_key = neural_signal_processor.fetch1('KEY')

        # find all directories in raw path
        raw_path = self.getrawpath(monkey_key['monkey'], rig_key['rig'], task_key['task'])
        raw_dir = sorted(list(os.listdir(raw_path)))

        if dates:
            # restrict dates based on user list
            session_dates = [d for d in raw_dir if d in dates]
        else:
            # get all dates from directory list
            session_dates = [d for d in raw_dir if re.search(r'\d{4}-\d{2}-\d{2}',d) is not None]

        # filter session dates by those not in table
        session_dates = [date for date in session_dates if not self & {'session_date': date}]

        for date in session_dates:

            session_path = raw_path + date + '/'
            session_files = os.listdir(session_path)

            # ensure behavior directory exists
            try:
                if task & {'task_controller_hardware':'Speedgoat'}:
                    behavior_dir = 'speedgoat'

                next(filter(lambda x: x==behavior_dir, session_files))

            except StopIteration:
                print('Missing behavior files for session {}'.format(date))

            else:         
                # ensure ephys directory exists
                try:
                    if nsp_key['hardware'] == 'Cerebus': # will add IMEC for new probes
                        ephys_dir = 'blackrock'

                    next(filter(lambda x: x==ephys_dir, session_files))

                except StopIteration:
                    print('Missing ephys files for session {}'.format(date))
                    
                else:
                    # session key
                    session_key = dict(session_date=date, **monkey_key)
                    
                    # insert session
                    self.insert1(dict(**session_key, **rig_key, **task_key))

                    # insert notes
                    try:
                        notes_files = next(x for x in session_files if re.search('.*notes\.txt',x))
                    except StopIteration:
                        print('Missing notes for session {}'.format(date))
                    else:
                        with open(session_path + notes_files,'r') as f:
                            self.Notes.insert1(dict(**session_key, session_notes_id=0, session_notes=f.read()))

                    # insert neural signal processor
                    self.Hardware.insert1(dict(**session_key, **nsp_key))

# -------------------------------------------------------------------------------------------------------------------------------
# LEVEL 2
# -------------------------------------------------------------------------------------------------------------------------------

@schema
class BehaviorRecording(dj.Imported):
    definition = """
    # Behavior recording, imported from Speedgoat files
    -> Session
    ---
    behavior_summary_file_path: varchar(1012) # path to summary file (temporary)
    behavior_sample_rate = 1e3: smallint unsigned # sampling rate for behavioral data (Hz)
    """

    key_source = Session - 'session_problem'
    
    def make(self, key):
        
        session_key = (Session & key).fetch1()
        
        # path to raw data
        raw_path = Session.getrawpath(session_key['monkey'],session_key['rig'],session_key['task']) + str(key['session_date'])
        
        # identify task controller
        task_controller_hardware = (Task & Session & session_key).fetch1('task_controller_hardware')

        if task_controller_hardware == 'Speedgoat':

            # path to speedgoat files
            speedgoat_path = raw_path + '/speedgoat/'
            speedgoat_files = list(os.listdir(speedgoat_path))

            # speedgoat summary file
            summary_file = next(filter(lambda f: re.search('.*\.summary',f), speedgoat_files))

            # ensure file path is "global" (i.e., relative to U19 server)
            key['behavior_summary_file_path'] = (reference.EngramPath & {'engram_tier':'locker'}).ensureglobal(speedgoat_path + summary_file)

        # behavior sample rate
        key['behavior_sample_rate'] = int(1e3)
        
        # insert key
        self.insert1(key)


@schema
class EphysRecording(dj.Imported):
    definition = """
    # Electrophysiological recording
    -> Session
    ephys_file_id: tinyint unsigned # file ID
    ---
    ephys_file_path: varchar(1012) # file path (temporary until issues with filepath attribute are resolved)
    ephys_sample_rate: smallint unsigned # sampling rate for ephys data (Hz)
    ephys_duration: double # recording duration (s)
    """

    class Channel(dj.Part):
        definition = """
        # Ephys channel header
        -> master
        channel_index: smallint unsigned # channel index in data array
        ---
        channel_id = null: smallint unsigned # channel ID used by Blackrock system
        channel_label: enum('brain', 'emg', 'sync', 'stim')
        """
    
    key_source = Session - 'session_problem'

    def make(self, key):
        
        session_key = (Session & key).fetch1()

        # path to raw data
        raw_path = Session.getrawpath(session_key['monkey'],session_key['rig'],session_key['task']) + str(session_key['session_date'])

        # fetch neural signal processor
        session_hardware = (Session.Hardware & session_key) * equipment.Hardware
        neural_signal_processor = (session_hardware & {'hardware_category': 'neural signal processor'}).fetch1('hardware')

        if neural_signal_processor == 'Cerebus':

            # path to blackrock files
            blackrock_path = raw_path + '/blackrock/'
            blackrock_files = list(os.listdir(blackrock_path))

            # path to NSx files
            nsx_files = [f for f in blackrock_files if re.search(r'.*(emg|neu|neu_emg)_00\d\.ns\d',f) is not None]
            nsx_path = [blackrock_path + f for f in nsx_files]

            for i, pth in enumerate(nsx_path):

                key['ephys_file_id'] = i
                primary_key = key.copy()

                # read NSx file
                nsx_file = NsxFile(pth)

                # read data from first channel
                nsx_data = nsx_file.getdata(nsx_file.extended_headers[0]['ElectrodeID'])

                # pull sample rate and recording duration
                key['ephys_sample_rate'] = int(nsx_data['samp_per_s'])
                key['ephys_duration'] = nsx_data['data_time_s']

                # ensure file path is "global" (i.e., relative to U19 server)
                key['ephys_file_path'] = (reference.EngramPath & {'engram_tier':'locker'}).ensureglobal(pth)

                # insert self
                self.insert1(key)

                # insert channel header information //TODO double check the map files use the ID and not the label
                for j, elec in enumerate(nsx_file.extended_headers):
                    key = primary_key.copy()
                    key['channel_index'] = j
                    key['channel_id'] = elec['ElectrodeID']
                    if re.search('^\d',elec['ElectrodeLabel']):
                        key['channel_label'] = 'brain'

                    elif re.search('ainp[1-8]$', elec['ElectrodeLabel']):
                        key['channel_label'] = 'emg'

                    elif elec['ElectrodeLabel'] == 'ainp15':
                        key['channel_label'] = 'stim'

                    elif elec['ElectrodeLabel'] == 'ainp16':
                        key['channel_label'] = 'sync'

                    self.Channel.insert1(key)

                # close file
                nsx_file.close()

# -------------------------------------------------------------------------------------------------------------------------------
# LEVEL 3
# -------------------------------------------------------------------------------------------------------------------------------

@schema
class BrainChannelGroup(dj.Manual):
    definition = """
    -> EphysRecording
    -> reference.BrainRegion
    -> equipment.ElectrodeArray.proj(brain_array_id = 'electrode_array_id')
    brain_channel_group_id: tinyint unsigned
    ---
    -> equipment.ElectrodeArrayConfig.proj(brain_array_config_id = 'electrode_array_config_id')
    hemisphere: enum('left', 'right')         # brain hemisphere
    probe_depth = null: decimal(5,3)          # depth of probe electrode (mm)
    brain_channel_group_notes: varchar(4095) # notes for the channel set
    """

    class Channel(dj.Part):
        definition = """
        # Channel number in recording file
        -> master
        -> EphysRecording.Channel
        ---
        brain_channel: smallint unsigned # brain channel index in group
        """


@schema
class EmgChannelGroup(dj.Manual):
    definition = """
    -> EphysRecording
    -> reference.Muscle
    -> equipment.ElectrodeArray.proj(emg_array_id = 'electrode_array_id')
    emg_channel_group_id: tinyint unsigned
    ---
    -> equipment.ElectrodeArrayConfig.proj(emg_array_config_id = 'electrode_array_config_id')
    emg_channel_group_notes: varchar(4095) # notes for the channel set
    """

    class Channel(dj.Part):
        definition = """
        # Channel number in recording file
        -> master
        -> EphysRecording.Channel
        ---
        emg_channel: smallint unsigned # EMG channel index in group
        emg_channel_quality: enum('sortable', 'hash', 'dead') # EMG channel quality
        """