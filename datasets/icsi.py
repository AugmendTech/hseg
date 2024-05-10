import os.path

import json
import xml.etree.ElementTree as ET

import structlog
logger = structlog.get_logger("base")

here = os.path.dirname(os.path.realpath(__file__))

from .data_utils import to_hhmmss, strip_key, AnnoTreeNode

'''
Token types:
    *None: Non-text token (e.g. "breath-laugh")
    *HYPH: Hyphen "-" => Included without spacing
    *W: Word (actual text) => Included
    #LQUOTE: Opening quote "
    #RQUOTE: Closing quote "
    *TRUNCW: Truncated (partial) word => Discarded or included as a word
    *QUOTE: Quote:
        single => Treat as APOSS
        double => Either LQUOTE or RQUOTE depending on positioning
    *ABBR: Abbreviation or special name => treated as a word
    *LET: Letter spelled-out => Treated as a word. This do not cover all cases: e.g. I(LET)Ds(W) is rendered as I Ds
        That said if we always append then other cases fail: e.g. O(LET)O(LET)two(W) rendered as OOtwo instead of O O two
        Cant be perfect!
    *CM: Comma => Included, with space only after
    *SYM: Special symbol: Either @ or - => @ is discarded, - is treated as HYPH but with spacing.
    *.: Ending symbols: ".", "!" or "?" => Obviously included
    *APOSS: Apostrophe "'" accompanied by one or more characters (e.g. from "That's" the "'s" part) => Include, no spacing
    *CD: Digit => Included
'''






class ICSIDataset:

    def __init__(self,timed_utterances=False,restricted=False):


        # Minimum allowed segment. Segments below this size will be appended to the next
        # segment or if this does not exist, the previous one.
        self.MIN_SEGMENT_SIZE = 10

        
        self.meta_file = f"{here}/ICSI/ICSI-metadata.xml"
        self.anno_dir = f"{here}/ICSI/Contributions/TopicSegmentation"
        self.seg_dir = f"{here}/ICSI/Segments"
        self.word_dir = f"{here}/ICSI/Words"

        # If we want meeting entries to have a time range
        self.timed_utterances = timed_utterances

        metadata_xml_fnm = self.meta_file
        metadata_xml_tree = ET.parse(metadata_xml_fnm) 
        metadata_root = metadata_xml_tree.getroot() 

        topic_fnms = os.listdir(self.anno_dir)
        meetings = sorted([fnm.split(".")[0] for fnm in topic_fnms if fnm.endswith(".xml")])

        agents = metadata_root.find('agents')
        speakers = [child.attrib["name"] for child in agents]

        if restricted:
            self.meetings = meetings[:5]
        else:
            self.meetings = meetings
            
        self.speakers = speakers


    def load_dataset(self):
        # Loads all words
        self.load_all_words()

        # Loads seg files and uses words to build segments.
        self.load_all_utterances()

        # Loads annotation tree
        self.load_anno_tree()



    def load_all_words(self):

        self.words = {}

        for meeting in self.meetings:
            self.words[meeting] = self.load_meeting_words(meeting)


    def load_meeting_words(self,meeting):

        # ICSI contain a word file for every meeting and speaker
        # This file is essentially an index of all spoken words
        # (+ non-verbal stuff)

        # Here, for each meeting and speaker we have a list of
        # words "in-order" and an index translating a word key
        # into its position in the list. This is needed for
        # parsing segments

        word_dir = self.word_dir
        speakers = self.speakers

        meeting_words = {}

        for speaker in speakers:

            quote_stack = []

            words_xml_fnm = f"{word_dir}/{meeting}.{speaker}.words.xml"

            if not os.path.isfile(words_xml_fnm):
                # Sometimes files won't exist, since not every speaker was present
                # in every meeting.
                logger.warning(f"File not found: {words_xml_fnm} => Skipping")
                continue

            root = ET.parse(words_xml_fnm).getroot() 

            meeting_words[speaker] = {
                "words": [],
                "index": {}
            }
            
            for child in root:
                
                key = child.attrib["{http://nite.sourceforge.net/}id"]

                # Words that do not contain the "c" attribute correspond to
                # comments or other non-spoken entries. These will be included
                # as placeholder None entries.
                word_type = child.attrib.get("c",None)
                text = child.text

                # Contains the logic for treating each word entry according to its type
                word = self.make_word_entry(word_type,text,quote_stack)

                meeting_words[speaker]["words"].append(word)
                meeting_words[speaker]["index"][key] = len(meeting_words[speaker]["words"])-1

            assert len(meeting_words[speaker]["words"]) == len(root)
            assert len(meeting_words[speaker]["index"]) == len(root)

        return meeting_words




    def load_all_utterances(self):


        self.index = {}

        for meeting in self.meetings:

            self.index[meeting] = {}

            meeting_utterances = self.load_meeting_utterances(meeting)

            entries = []

            for speaker in meeting_utterances:
                entries.extend(meeting_utterances[speaker])

                self.index[meeting][speaker] = {}


            sot = min([entry["start"] for entry in entries if entry["start"] is not None])

            for i, entry in enumerate(entries):
                entry["sot"] = sot
                key = entry["key"]
                speaker = entry["speaker"]

                self.index[meeting][speaker][key] = entry


    def load_meeting_utterances(self,meeting):

        seg_dir = self.seg_dir

        utterances = {}


        logger.info(f"Extracting utterances for meeting {meeting}")

        logger.info(f"Speakers: {self.words[meeting].keys()}")


        for speaker in self.words[meeting]:

            logger.info(f"Extracting utterances for meeting {meeting} and speaker {speaker}")
            segs_xml_fnm = f"{seg_dir}/{meeting}.{speaker}.segs.xml"

            if not os.path.isfile(segs_xml_fnm):
                logger.error(f"Act file {segs_xml_fnm} not found, while words file exists. Are you missing an act file?")
                #exit(-1)
                continue


            segs = []

            for child in ET.parse(segs_xml_fnm).getroot():
                if child.attrib.get("type","")=="supersegment":
                    for grandchild in child:
                        segs.append(grandchild)
                else:
                    segs.append(child)

            utterances[speaker] = []

            for seg in segs:

                if not list(seg):
                    continue
                
                seg_id = seg.attrib["{http://nite.sourceforge.net/}id"]
                seg_start = seg.attrib["starttime"]
                seg_end = seg.attrib["endtime"]
                word_range = list(seg)[0].attrib["href"].split("#")[-1]

                if ".." in word_range:
                    start_key, end_key = word_range.split("..")
                else:
                    start_key = end_key = word_range

                start_key = strip_key(start_key)
                end_key = strip_key(end_key)

                start_idx = self.words[meeting][speaker]["index"][start_key]
                end_idx = self.words[meeting][speaker]["index"][end_key]


                utterance = None

                for t in range(start_idx,end_idx+1):

                    word = self.words[meeting][speaker]["words"][t]

                    if word is None:
                        continue

                    utterance = self.absorb_token(utterance, word)

                if utterance:
                    utterance["speaker"] = speaker
                    utterance["key"] = seg_id
                    utterance["start"] = float(seg_start) if seg_start else None
                    utterance["end"] = float(seg_end) if seg_end else None

                    # This only happens for 3 utterances in the whole corpus
                    if utterance["end"] is None:
                        utterance["end"] = utterance["start"] + 1.0
                    utterances[speaker].append(utterance)
                
        return utterances


    def absorb_token(self, utterance, token):


        if utterance is None:
            return token

        spaced = utterance.get("rspace", True) and token["lspace"]
        
        suffix = ""

        if spaced:
            suffix += " "

        suffix += token["text"]

        utterance["text"] += suffix
        utterance["rspace"] = token["rspace"]

        return utterance




    def make_word_entry(self, word_type, text, quote_stack):

        # tag: is the type of word
        # lspace: does the netry warrant a left-side space
        # rspace: does the netry warrant a right-side space
        # text: text content of entry

        entry = {
                "tag": word_type,
                "lspace": True,
                "rspace": True,
                "text": text,
            }

        if word_type in ["W", "TRUNCW"]:

            # words that start with ' are treated as APOSS (apostrophe) entries
            if text[0]=="'":
                return self.make_word_entry("APOSS",text,quote_stack)
            else:
                return entry

        # Abbreviations, letters and digits are all treated as text
        if word_type == "ABBR": 
            return entry

        if word_type == "LET":
            return entry
        
        if word_type == "CD":
            return entry
        
        # Symbols are either hyphens or @ (unknown purpose)
        # - : treated as HYPH
        # @ : discarded

        if word_type == "SYM":
            if text=="-":
                return self.make_word_entry("HYPH",text,quote_stack)
            else:
                return None
            
        if word_type == "HYPH":
            # No spacing for hyphens
            entry["lspace"] = False
            entry["rspace"] = False
            return entry
        
        if word_type == "CM":
            # No left space for commas
            entry["lspace"] = False
            return entry
        
        if word_type == ".":
            # No left space for periods
            entry["lspace"] = False
            return entry
        
        if word_type == "APOSS":
            # No left space for entries starting with '
            entry["lspace"] = False
            return entry
        
        # This is the juicy terittory
        # ICSI can have QUOTE, LQUOTE or RQUOTE
        # LQUOTE and RQUOTE denote left and right double quotes
        # QUOTE can be single in which case we treat is as apostrophe
        if word_type == "LQUOTE":
            if text=="'":
                entry["tag"] = "APOSS"
                entry["lspace"] = False
                entry["rspace"] = False
                return entry
            quote_stack.append("LEFT")
            entry["rspace"] = False
            return entry

        if word_type == "RQUOTE":
            if text=="'":
                entry["tag"] = "APOSS"
                entry["lspace"] = False
                entry["rspace"] = False
                return entry
            entry["lspace"] = False
            if not quote_stack:
                logger.error("Mismatched quotes. Found closing quote with no opening quote.")
            else:
                quote_stack.pop()
            return entry

        if word_type == "QUOTE":
            if text=="'":
                entry["tag"] = "APOSS"
                entry["lspace"] = False
                entry["rspace"] = False
                return entry
            if not quote_stack:
                return self.make_word_entry("LQUOTE",text,quote_stack)
            else:
                return self.make_word_entry("RQUOTE",text,quote_stack)

        if word_type is None:
            return None
        
        raise Exception("UnsupportedType",word_type)


    def build_anno(self, xml_node):

        anno_node = AnnoTreeNode()

        if "root" in xml_node.tag:
            anno_node.tag = "root"
        else:
            anno_node.tag = "topic"


        utt_keys = []

        for entry in xml_node:

            if entry.tag=="topic":
                if entry:
                    anno_node.nn.append(self.build_anno(entry))
                continue

            meta, utt_content = entry.attrib["href"].split("#")
            speaker = meta.split(".")[1]

            if ".." in utt_content:
                start_utt, end_utt = utt_content.split("..")

                start_utt = strip_key(start_utt)
                end_utt = strip_key(end_utt)

                start_tokens = start_utt.split(".")
                end_tokens = end_utt.split(".")

                start_idx = int(start_tokens[-1].replace(",",""))
                end_idx = int(end_tokens[-1].replace(",",""))
                stem = ".".join(start_tokens[:-1])


                utt_keys = []
                for i in range(start_idx,end_idx+1):

                    utt_id = str(i)

                    if i>=1000:
                        utt_id = utt_id[:-3] + "," + utt_id[-3:]

                    utt_keys.append(f"{speaker}:{stem}.{utt_id}")

            else:
                utt_keys = [f"{speaker}:{strip_key(utt_content)}"]

            for key in utt_keys:
                utt = AnnoTreeNode()
                utt.tag = "utterance"
                utt.key = key
                anno_node.nn.append(utt)

        return anno_node

    def register_anno_node(self,anno_index, node):

        path = node.path

        if path in anno_index:
            logger.error(f"Duplicate node path: {path}")
            exit(-1)
        
        anno_index[path] = node


    def normalize_anno_tree(self, path, node, anno_index):

        nn = node.nn

        node.path = path
        self.register_anno_node(anno_index,node)

        node.is_leaf = all([child.tag=="utterance" for child in nn])

        normalized_nn = []

        branch_id = 0

        while nn:

            if nn[0].tag=="utterance":
                composed_topic_keys = []
                while nn and nn[0].tag=="utterance":
                    composed_topic_keys.append(nn.pop(0).key)

                if node.is_leaf:
                    node.keys = composed_topic_keys
                    node.nn = []
                    return node
                
                topic_node = AnnoTreeNode()
                topic_node.tag = "topic"
                topic_node.composed = True
                topic_node.path = path+"."+str(branch_id)
                self.register_anno_node(anno_index,topic_node)
                
                branch_id += 1
                topic_node.keys = composed_topic_keys
                normalized_nn.append(topic_node)
                topic_node.is_leaf = True
                topic_node.nn = []
                continue

            normalized_nn.append(self.normalize_anno_tree(path+"."+str(branch_id),nn.pop(0), anno_index))
            branch_id += 1
            node.is_leaf = False

        node.nn = normalized_nn
        return node


    def print_anno_tree(self,anno_index):

        paths = sorted(list(anno_index.keys()))

        print("\n\n\n++++++++++++++++++")
        print("==================")
        for path in paths:
            node = anno_index[path]
            print(path)
            print([f"{child.path}:{child.tag}" for child in node.nn])
            if node.is_leaf:
                print(f"{node.keys[0]}=>{node.keys[-1]}")
            print("==================")
        print("++++++++++++++++++\n\n\n")


    def get_parent_path(self,path):
        return ".".join(path.split(".")[:-1])


    def delete_anno_leaf(self,anno_index,path):

        logger.info(f"Deleting {path}")
        node = anno_index[path]
        parent_path = self.get_parent_path(path)

        parent = anno_index[parent_path]
        parent.nn = [node for node in parent.nn if node.path!=path]

        if not parent.nn:
            logger.error(f"Unsupported case: Parent node now has no children.")
        del anno_index[path]

        return node.keys

    def finalize_anno_tree(self, anno_index, anno_root):

        anno_leaves = self.discover_anno_leaves(anno_root)
        for leaf in anno_leaves:
            if not leaf.keys:
                self.delete_anno_leaf(anno_index, leaf.path)


    def discover_anno_leaves(self, anno_root):

        stack = [anno_root]
        curr = anno_root

        leaves = []

        while stack:

            node = stack.pop()

            if node.is_leaf:
                leaves.append(node)

            for child in node.nn[::-1]:
                stack.append(child)

        return leaves


    def attach_meeting_notes(self, meeting, anno_root):
        
        duplicate_check_list = {}

        anno_leaves = self.discover_anno_leaves(anno_root)

        for leaf in anno_leaves:

            filtered_keys = []
            convo = []

            for key in leaf.keys:
                speaker, utt_key = key.split(":")

                if utt_key not in self.index[meeting][speaker]:
                    #logger.warning(f"Pruning key: {key}")
                    continue

                if key in duplicate_check_list:
                    logger.warning(f"Duplicate key: {key} {leaf.path} and {duplicate_check_list[key]}")
                    #print(self.index[meeting][speaker][utt_key])
                    #exit(-1)
                filtered_keys.append(key)
                duplicate_check_list[key] = leaf.path
                convo.append(self.index[meeting][speaker][utt_key])

            leaf.keys = filtered_keys
            leaf.convo = convo


    def compose_utterance(self,utterance):
        speaker = utterance["speaker"]
        sot = utterance["sot"]
        start = round(utterance["start"] - sot,1) if utterance["start"] is not None else None
        end = round(utterance["end"] - sot,1) if utterance["end"] is not None else None
        text = utterance["text"]
        key = utterance["key"]

        if self.timed_utterances:
            return f"[{to_hhmmss(start,include_milli=True)}-{to_hhmmss(end,include_milli=True)}] Speaker {speaker}: {text}"
        return f"-{text}"

    def load_anno_tree(self):

        anno_dir = self.anno_dir

        self.annos = {}
        self.leaves = {}
        self.anno_indices = {}

        for meeting in self.meetings:

            anno_xml_fnm = f"{anno_dir}/{meeting}.topic.xml"

            if not os.path.isfile(anno_xml_fnm):
                logger.error(f"Anno file missing: {anno_xml_fnm}")
                exit(-1)


            root = ET.parse(anno_xml_fnm).getroot()

            anno_root = self.build_anno(root)

            anno_index = {}
            anno_root = self.normalize_anno_tree("*",anno_root,anno_index)

            self.attach_meeting_notes(meeting, anno_root)
            self.finalize_anno_tree(anno_index, anno_root)

            self.annos[meeting] = anno_root
            self.anno_indices[meeting] = anno_index


    def compose_meeting_notes(self):

        self.notes = {}
        self.labs = {}
        self.transitions = {}
        self.raw_transitions = {}

        for meeting in self.meetings:

            self.notes[meeting] = []
            self.raw_transitions[meeting] = []
            anno_root = self.annos[meeting]

            prev_leaf_id = 0

            anno_leaves = self.discover_anno_leaves(anno_root)


            for leaf_id, leaf in enumerate(anno_leaves):

                for utt in leaf.convo:
                    if leaf_id!=prev_leaf_id:
                        self.raw_transitions[meeting].append(1)
                        prev_leaf_id = leaf_id
                    else:
                        self.raw_transitions[meeting].append(0)
                    utt["composite"] = self.compose_utterance(utt)
                    self.notes[meeting].append(utt)

            raw_transitions = self.raw_transitions[meeting]
            transitions = raw_transitions.copy()

            for i, _ in enumerate(raw_transitions):
                if sum(transitions[i - self.MIN_SEGMENT_SIZE : i]) > 0:
                    transitions[i] = 0
            self.transitions[meeting] = transitions