import copy
import json
import uuid
import jmespath

class JSONGraph:
    # takes JSON-LD graphs,detects the main entity and rebuilds the graph as JSON using the main entity as root
    # it further strips ALL prefixes so the graph can easily be queried using JMESPATH
    # I know it looks strange to use this instead of RDFLib but extracting metadata from a graph structure is sometimes
    # a challenge and deciding on a root entity and using jmespath makes life a bit easier.
    # Further in practice in particular embedded JSON-LD is not always standard compliant
    # wrong namespaces or variants of namespace http://schema.org https://www.schema.org http://www.schema.org/ etc.
    # and due to some frustrating experience with context file loading by RDFlib which may take up to a minute
    # I just decided to try this workaround.

    def __init__(self):
        self.mainNode = None
        self.nodes = {}
        self.jsonld = None
        self._stats = {'properties': 0, 'outlinks': 0, 'inlinks': 0};


    def parse(self, jsonstr, rootNodeID = None):
        # parses a given JSON-LD string representing a graphs and returns a rebuilt new, nested JSON-LD
        # which starts with a root node which can either be defined using rootNodeID or is alternatively
        # determined as the 'most important' node called self.mainNode; see scoring in _setNodesInfo
        self.jsonld = json.loads(jsonstr)
        # basically three possibilities:
        # 1: a simple list containing other graphs
        # 2: a @graph list containg other graphs
        # 3: simply one graph
        if isinstance(self.jsonld, list):
            branches = self.jsonld
        else:
            branches = self.jsonld.get('@graph')
        if not branches:
            branches = [self.jsonld]

            #parse, detect individual typed nodes and rebuild graph using the main node as starting point
        if isinstance(branches, list):
            for branch in branches:
                self._setNodes(branch)
            self._setNodesInfo()
            if rootNodeID and self.nodes.get(rootNodeID):
                rootNode = self.nodes[rootNodeID]
            else:
                rootNode = self.nodes[self.mainNode]
            if rootNode:
                root = rootNode['dict']
                #print('ROOT: ', mainnode)
                # the graph is re-created so that the main node is the root node in the resulting JSON
                # however this may just be a subgraph, since it is just rebuilt starting at root
                self.jsonld = self.expandNode(root)
            #print('REBUILT JSON: ', json.dumps(self.jsonld, indent=2))

    def _setNodes(self, branch, fromprop = None):
        def strip_node_prefixes(node):
            """Recursively strip all prefixes from dict keys and @type values."""
            if isinstance(node, dict):
                new_node = {}
                for key, value in node.items():
                    # Strip prefix from key
                    local_key = key.split(':')[-1]
                    # Recurse into nested dicts or lists
                    if isinstance(value, dict):
                        value = strip_node_prefixes(value)
                    elif isinstance(value, list):
                        value = [strip_node_prefixes(v) if isinstance(v, dict) else v for v in value]
                    # Strip prefix from @type values if string or list
                    # this is necessary for easy node by name retrieval, see: getNodesByType
                    # but using the _local_name it becomes deprecated...
                    '''if local_key == '@type':
                        if isinstance(value, str):
                            value = value.split(':')[-1]
                        elif isinstance(value, list):
                            value = [v.split(':')[-1] if isinstance(v, str) else v for v in value]'''
                    new_node[local_key] = value
                return new_node
            return node
        # --------------------------------------------------------
        # Process only dicts
        # --------------------------------------------------------
        if isinstance(branch, dict):
            # Skip single-ID nodes
            if len(branch) == 1 and '@id' in branch:
                return
            # Assign ID if missing
            branch_id = branch.get('@id', 'urn:uuid:' + str(uuid.uuid4()))
            branch['@id'] = branch_id
            if branch_id in self.nodes:
                print(f"DUPLICATE NODE ID: {branch_id}")
            noprops = len(branch)
            self._stats['properties'] = max(self._stats['properties'], noprops)
            # Strip prefixes recursively
            branch = strip_node_prefixes(branch)
            # Store node
            self.nodes[branch_id] = {
                'dict': branch,
                'id': branch_id,
                'outlinks': 0,
                'inlinks': 0,
                'properties': noprops,
                'from_prop': fromprop
            }
            # Iterate safely over a snapshot of keys
            for nodeprop in list(branch.keys()):
                nodecand = branch[nodeprop]
                # LIST
                if isinstance(nodecand, list):
                    for nidx, ncand in enumerate(nodecand):
                        if isinstance(ncand, dict):
                            if len(ncand) == 1 and '@id' in ncand:
                                nodecand[nidx] = ncand['@id']
                            else:
                                self._setNodes(ncand,nodeprop)
                # DICT
                elif isinstance(nodecand, dict):
                    if len(nodecand) == 1 and '@id' in nodecand:
                        branch[nodeprop] = nodecand['@id']
                    else:
                        node_id = nodecand.get('@id', 'urn:uuid:' + str(uuid.uuid4()))
                        nodecand['@id'] = node_id
                        branch[nodeprop] = node_id
                        self._setNodes(nodecand,nodeprop)

    def _setNodesInfo(self):
        main_entity_score = 0

        for nodekey, node in self.nodes.items():
            outcands = []

            # Collect all string-valued outgoing links
            for prop, value in node['dict'].items():
                if prop != '@id':
                    if isinstance(value, str):
                        outcands.append(value)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, str):
                                outcands.append(item)

            # Update inlinks/outlinks counts
            for linkid in outcands:
                if linkid in self.nodes:
                    self.nodes[linkid]['inlinks'] += 1
                    self.nodes[nodekey]['outlinks'] += 1

                    if self.nodes[linkid]['inlinks'] >= self._stats.get('inlinks', 0):
                        self._stats['inlinks'] = self.nodes[linkid]['inlinks']

                    if self.nodes[linkid]['outlinks'] >= self._stats.get('outlinks', 0):
                        self._stats['outlinks'] = self.nodes[linkid]['outlinks']

            # Compute node score
            prp_score = 0
            sbj_score = 0

            if self._stats.get('properties', 0) > 0:
                prp_score = self.nodes[nodekey]['properties'] / self._stats['properties']

            if self._stats.get('inlinks', 0) > 0:
                sbj_score = 0.5 * (1 - self.nodes[nodekey]['inlinks'] / self._stats['inlinks'])

            comb_score = prp_score + sbj_score / 2

            # Update main node ID if score is highest
            if comb_score > main_entity_score:
                main_entity_score = comb_score
                self.mainNode = nodekey

    def expandNode(self, node, memo=None, expanding=None):
        if memo is None:
            memo = {}
        if expanding is None:
            expanding = set()

        if isinstance(node, str):
            if node in self.nodes:
                return self.expandNode(self.nodes[node]['dict'], memo, expanding)
            return node

        if not isinstance(node, dict):
            return node

        node_id = node.get('@id')

        # If already expanded, return only a reference to avoid cycles
        if node_id and node_id in memo:
            return {"@id": node_id}

        # Detect true cycles (optional)
        if node_id and node_id in expanding:
            raise ValueError(f"Circular reference detected at @id: {node_id}")

        if node_id:
            expanding.add(node_id)

        expanded = {}
        if node_id:
            memo[node_id] = expanded

        for key, value in node.items():
            if key in ['url']: #don't expand url properties these are not @id references
                expanded[key] = value
                continue

            if isinstance(value, str):
                if value in self.nodes and value != node_id:
                    expanded[key] = self.expandNode(
                        self.nodes[value]['dict'], memo, expanding
                    )
                else:
                    expanded[key] = value

            elif isinstance(value, list):
                expanded[key] = [self.expandNode(item, memo, expanding) for item in value]

            elif isinstance(value, dict):
                expanded[key] = self.expandNode(value, memo, expanding)

            else:
                expanded[key] = value

        if node_id:
            expanding.remove(node_id)

        return expanded

    def _local_name(self, t):
        # Helper method to retrieve a local name (without namespace prefix)
        if not t:
            return None
        return t.split('/')[-1].split(':')[-1]

    def getNodesByType(self, target_type, excludeMainEntity = True):
        # Normalize input: always work with a list of types
        if isinstance(target_type, str):
            target_types = {target_type}
        else:
            target_types = set(target_type)

        results = []

        for node in self.nodes.values():
            types = node['dict'].get('@type')

            '''if isinstance(types, str):
                node_types = {types}
            elif isinstance(types, list):
                node_types = set(types)
            else:
                continue  # skip if no @type'''

            if isinstance(types, str):
                node_types = {self._local_name(types)}
            elif isinstance(types, list):
                node_types = {self._local_name(t) for t in types}
            else:
                continue  # skip if no @type

            # intersection means node has at least one desired type
            if node_types & target_types:
                if excludeMainEntity:
                    if self.mainNode != node['dict']['@id']:
                        results.append({'graph': self.expandNode(node['dict']['@id']), 'from_prop': node['from_prop']})
                else:
                    results.append({'graph': self.expandNode(node['dict']['@id']), 'from_prop': node['from_prop']})
        return results

    def query(self, query):
        result = {}
        # a method to perform jmespath queries on the JSON
        result = jmespath.search(query, self.jsonld)
        result  = {k: v for k, v in result.items() if v is not None}
        return result