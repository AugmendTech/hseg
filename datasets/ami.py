import os.path

import json
import xml.etree.ElementTree as ET

import structlog

logger = structlog.get_logger("base")

here = os.path.dirname(os.path.realpath(__file__))

from .data_utils import to_hhmmss, strip_key, AnnoTreeNode


class AMIDataset:

    def __init__(self, timed_utterances=False,restricted=False):

        # Minimum allowed segment. Segments below this size will be appended to the next
        # segment or if this does not exist, the previous one.
        self.MIN_SEGMENT_SIZE = 10

        self.meta_file = f"{here}/AMI/AMI-metadata.xml"
        self.anno_dir = f"{here}/AMI/topics"
        self.seg_dir = f"{here}/AMI/segments"
        self.word_dir = f"{here}/AMI/words"

        # If we want meeting entries to have a time range
        self.timed_utterances = timed_utterances

        metadata_xml_fnm = self.meta_file
        metadata_xml_tree = ET.parse(metadata_xml_fnm)
        metadata_root = metadata_xml_tree.getroot()

        topic_fnms = os.listdir(self.anno_dir)
        meetings = sorted([fnm.split(".")[0] for fnm in topic_fnms])

        agents = metadata_root.find("agents")
        speakers = [child.attrib["name"] for child in agents]

        if restricted:
            self.meetings = meetings[:5]
        else:
            self.meetings = meetings
            
        self.speakers = speakers

    def load_dataset(self):
        # Loads all words
        self.load_all_words()

        self.utterances = {}

        for meeting in self.meetings:
            self.utterances[meeting] = {}

        # Loads annotation tree
        self.load_anno_tree()

    def load_all_words(self):

        self.words = {}

        for meeting in self.meetings:
            self.words[meeting] = self.load_meeting_words(meeting)

    def load_meeting_words(self, meeting):

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

            meeting_words[speaker] = {"words": [], "index": {}}

            for child in root:

                key = child.attrib["{http://nite.sourceforge.net/}id"]
                text = child.text

                # Words that do not contain the "c" attribute correspond to
                # comments or other non-spoken entries. These will be included
                # as placeholder None entries.

                if text:
                    text = text.lstrip().rstrip()
                    word = {
                        "text": text,
                        "lspace": True,
                        "rspace": True,
                        "start": float(child.attrib["starttime"]),
                        "end": float(child.attrib["endtime"]),
                    }
                else:
                    word = None

                if text in [".", ",", "?", "!"]:
                    word["lspace"] = False

                meeting_words[speaker]["words"].append(word)
                meeting_words[speaker]["index"][key] = (
                    len(meeting_words[speaker]["words"]) - 1
                )

            assert len(meeting_words[speaker]["words"]) == len(root)
            assert len(meeting_words[speaker]["index"]) == len(root)

        return meeting_words


    def compose_utterance(self,utterance):
        speaker = utterance["speaker"]
        sot = 0.0#utterance["sot"]
        start = round(utterance["start"] - sot,1) if utterance["start"] is not None else None
        end = round(utterance["end"] - sot,1) if utterance["end"] is not None else None
        text = utterance["text"]
        key = utterance["key"]

        if self.timed_utterances:
            return f"[{to_hhmmss(start,include_milli=True)}-{to_hhmmss(end,include_milli=True)}] Speaker {speaker}: {text}"
        return f"-{text}"

    

    def mint_utterance(self,utt_content,speaker,meeting,utt_words):
        utt_text = ""
        rspace = False

        for w in utt_words:

            if w["lspace"] and rspace:
                utt_text += " "

            rspace = w["rspace"]

            utt_text += w["text"]

        utterance = {
            "key": utt_content,
            "speaker": speaker,
            "meeting": meeting,
            "start": utt_words[0]["start"],
            "end": utt_words[-1]["end"],
            "text": utt_text,
        }
        return utterance

    def segment_to_utterances(self, entries):


        utterances = []

        for entry in entries:
            meta, utt_content = entry.attrib["href"].split("#")
            meeting = meta.split(".")[0]
            speaker = meta.split(".")[1]

            word_index = self.words[meeting][speaker]


            if ".." in utt_content:

                start_word, end_word = utt_content.split("..")

                start_word = strip_key(start_word)
                end_word = strip_key(end_word)

                start_idx = word_index["index"][start_word]
                end_idx = word_index["index"][end_word]

                utt_words = []

                for i in range(start_idx, end_idx + 1):

                    word = word_index["words"][i]

                    if word is None:
                        continue

                    utt_words.append(word)

                    if word["text"][-1] in [".", "!", "?"]:
                        utterance = self.mint_utterance(utt_content,speaker,meeting,utt_words)
                        utterances.append(utterance)
                        utt_words = []

                if utt_words:
                    utterance = self.mint_utterance(utt_content,speaker,meeting,utt_words)
                    utterances.append(utterance)
            else:
                word_key = strip_key(utt_content)
                word_idx = word_index["index"][word_key]
                word = word_index["words"][word_idx]

                if word is None:
                    continue

                if "start" not in word:
                    print(word)
                    input()
                utterance = {
                        "key": utt_content,
                        "speaker": speaker,
                        "meeting": meeting,
                        "start": word["start"],
                        "end": word["end"],
                        "text": word["text"],
                    }
                utterances.append(utterance)
                

        for utterance in utterances:
            utterance["composite"] = self.compose_utterance(utterance)

        keys = [utt["key"] for utt in utterances]

        return keys, utterances


    def build_anno(self, anno_index, path, xml_node):

        anno_node = AnnoTreeNode()
        anno_node.path = path

        self.register_anno_node(anno_index, anno_node)

        branch_id = 0

        utterances = []

        children = [entry for entry in xml_node]
        anno_node.is_leaf = not any([child.tag=="topic" for child in children])

        if "root" in xml_node.tag:
            anno_node.tag = "root"
        elif anno_node.is_leaf:
            anno_node.tag = "leaf"
        else:
            anno_node.tag = "topic"

        while children:

            if "pointer" in children[0].tag:
                children.pop(0)
                continue

            if "topic" in children[0].tag:
                entry = children.pop(0)
                nn_path = f"{anno_node.path}.{branch_id}"
                anno_node.nn.append(self.build_anno(anno_index, nn_path, entry))
                branch_id += 1
                continue

            
            if "child" in children[0].tag:

                segments = []

                while children and "child" in children[0].tag:
                    segments.append(children.pop(0))

                keys, convo = self.segment_to_utterances(segments)
                
                if not keys:
                    raise Exception("NodeNoKeys", xml_node.tag)

                if not anno_node.is_leaf:

                    composed_topic = AnnoTreeNode()
                    composed_topic.keys = keys
                    composed_topic.convo = convo
                    composed_topic.tag = "leaf"

                    composed_topic.path = f"{anno_node.path}.{branch_id}"
                    composed_topic.is_leaf = True
                    self.register_anno_node(anno_index, composed_topic)

                    anno_node.nn.append(composed_topic)
                    branch_id += 1
                    continue
                else:
                    anno_node.keys = keys
                    anno_node.convo = convo
                    break

            raise Exception("NonSupportedNodetype",children[0].tag)
        
        if anno_node.is_leaf and not anno_node.keys:
            raise Exception("NodeNoKeys", xml_node.tag)


        return anno_node

    def register_anno_node(self, anno_index, node):

        path = node.path

        if path in anno_index:
            logger.error(f"Duplicate node path: {path}")
            exit(-1)

        anno_index[path] = node

    def print_anno_tree(self, anno_index):

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

            anno_index = {}
            anno_root = self.build_anno(anno_index, "*", root)

            self.annos[meeting] = anno_root
            self.anno_indices[meeting] = anno_index

            #self.print_anno_tree(anno_index)
            #input()
   

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