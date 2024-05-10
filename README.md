# This repo makes two contributions:

1. Code for extracting utterances and ground truth segmentation from ICSI and AMI.
2. Adapted versions of two unuspervised meetings segmentation approaches.

# ICSI and AMI datasets:

### AMI:
- Download the AMI corpus from here: https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip
- Create a folder named `AMI` in the `datasets` dir (`datasets/AMI/`) and extract it there.
### ICSI:
- Download the ICSI corpus from here: https://groups.inf.ed.ac.uk/ami/ICSICorpusAnnotations/ICSI_plus_NXT.zip
- Create a folder named `ICSI` in the `datasets` dir (`datasets/ICSI/`) and extract it there.

The two datasets are available via the classes `ICSIDataset` and `AMIDataset`


# Baselines

Both baselines are adapted to receive a desired number of segments K. The top K-1 splitting points are used to segment
the meeting into K segments.


## **Unsupervised Topic Segmentation of Meetings with BERT Embeddings**

- Paper: https://arxiv.org/abs/2106.12978
- Original repo: https://github.com/gdamaskinos/unsupervised_topic_segmentation

The code is adapted from the original repo and differs in two major ways:

- It uses OpenAI instead of Roberta embeddings.
- In the original repo the ICSI/AMI datasets were assumed to reside in some database and were thus unavailable.
We have adapted the code to use our version of ICSI and AMI as described above.

   
## **Unsupervised Dialogue Topic Segmentation in Hyperdimensional Space (Interspeech 2023)**

- Paper: https://arxiv.org/abs/2308.10464
- Original repo: https://github.com/seongminp/hyperseg

The original repo did not contain extracted data for ICSI/AMI. We have adapted the code to our version of ICSI and AMI as described above.

# Running

- The entry point is `main.py`
- You can invoke it as follows `python3 main.py --model MODEL_NAME --dataset DATASET_NAME --mid MEETING_ID`
- model: `bertseg` (BERT embeddings), `hyperseg` (hyperdimensional vectors), `random` (random segmentation), `equi` (equidistant segments), `view` (will print meeting in-order, segment by segment)
- dataset: `icsi` or `ami` 
- mid: 0-indexed meeting id as an integer (e.g. 1 will evaluate on the second meeting in the corpus)

- Only the first 5 meetings from each corpus are loaded to save time testing. To remove this restriction pass `restricted=False` to the dataset class constructor.
- For `bertseg` you will need to set up an environment variable named `OPENAI_API_KEY` with your OpenAI key, so that the embeddings can be extracted. Calls to the embeddings endpoint are inexpensive. We are using the `text-embedding-3-large` model. For more information on pricing, take a look here: https://openai.com/api/pricing/

- The original segment transitions are pruned so that segments have a minimum size of 10 utterances. In the end a plot is displayed comparing the original, pruned and inferred segment transitions points.


