function obj = getSchema
persistent OBJ
if isempty(OBJ)
    OBJ = dj.Schema(dj.conn, 'multitask_network', 'elomtest_multitask_network');
end
obj = OBJ;