import os, sys

import json


from baselines import RandomSeg, EquiSeg
import datasets

import matplotlib.pyplot as plt
from nltk.metrics import windowdiff


import structlog

logger = structlog.get_logger("base")


import argparse

parser = argparse.ArgumentParser()
parser.add_argument(
    "--model",
    type=str,
    required=True,
    choices=["bertseg", "hyperseg", "random", "equi", "view"],
)
parser.add_argument("--dataset", type=str, required=True, choices=["ami", "icsi"])
parser.add_argument("--mid", type=int, required=True)

args = parser.parse_args()

MODEL_NAME = args.model
DATASET = args.dataset
MID = args.mid


if DATASET == "icsi":
    dataset = datasets.ICSIDataset(restricted=True)
elif DATASET == "ami":
    dataset = datasets.AMIDataset(restricted=True)
else:
    raise Exception("UnsupportedDataset", DATASET)

dataset.load_dataset()
dataset.compose_meeting_notes()

meeting = dataset.meetings[MID]
entries = dataset.notes[meeting]

logger.info(f"Segmenting meeting {meeting}")

if MODEL_NAME == "view":
    anno_root = dataset.annos[meeting]
    leaves = dataset.discover_anno_leaves(anno_root)

    for leaf in leaves:
        print("\n++++++++++++++++++++++++++++++++++++")
        print(f"Segment leaf identifier: {leaf.path}")
        print("Segment transcript:")
        for entry in leaf.convo:
            print(entry["composite"])
        print("++++++++++++++++++++++++++++++++++++\n")
        input("Press any key + ENTER to continue...")
elif MODEL_NAME == "bertseg":
    from bertseg import BertSeg
    from configs import bertseg_configs

    model = BertSeg(configs=bertseg_configs, entries=entries)
elif MODEL_NAME == "hyperseg":
    from hyperseg import HyperSegSegmenter

    model = HyperSegSegmenter(entries=entries)
elif MODEL_NAME == "random":
    model = RandomSeg(entries=entries)
elif MODEL_NAME == "equi":
    model = EquiSeg(entries=entries)
else:
    raise Exception("UnsupportedModel", MODEL_NAME)


raw_transitions = dataset.raw_transitions[meeting]
transitions = dataset.transitions[meeting]

true_K = int(sum(transitions)) + 1
transitions_hat = model.segment_meeting(true_K)


logger.info(f"Ground truth K: {sum(transitions)}")
logger.info(f"K returned from model: {sum(transitions_hat)}")

diff_k = int(round(len(transitions) / (sum(transitions) * 2.0)))

tr_str = "".join([str(lab) for lab in transitions])
tr_hat_str = "".join([str(lab) for lab in transitions_hat])

loss = windowdiff(tr_str, tr_hat_str, diff_k)

logger.info(f"WinDiff:{loss}")

plt.subplot(3, 1, 1)
plt.title("Original segment transitions")
plt.plot(raw_transitions, color="r")
plt.subplot(3, 1, 2)
plt.title("Pruned segment transitions")
plt.plot(transitions)
plt.subplot(3, 1, 3)
plt.title("Inferred segment transitions")
plt.plot(transitions_hat, color="g")
plt.show()
