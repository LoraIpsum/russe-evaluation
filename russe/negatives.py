from pandas import read_csv
from time import time
from nlp.common import exists
import cPickle as pickle
import gzip
import codecs
from os.path import splitext, join
from collections import Counter
from nlp.morpho.mystem import get_pos
from collections import defaultdict

MAX_PMI = -0.02
MIN_LEN = 3
MULT_COEFF = 2


def merge_pos_and_neg(pos_fpath, neg_fpath, freq_fpath):
    output_fpath = splitext(pos_fpath)[0] + "-final.csv"

    # load resources 
    pos_df = read_csv(pos_fpath, ',', encoding='utf8')
    neg_df = read_csv(neg_fpath, ';', encoding='utf8')
    freq_df = read_csv(freq_fpath, '\t', encoding='utf8')

    freq = {r["word"]: r["freq"] for i, r in freq_df.iterrows()}
    pos = defaultdict(dict) 
    for i, r in pos_df.iterrows(): 
        pos[r["word1"]][r["word2"]] = freq[r["word2"]] if r["word2"] in freq else 1

    neg = defaultdict(dict) 
    for i, r in neg_df.iterrows(): 
        neg[r["word1"]][r["word2"]] = freq[r["word2"]] if r["word2"] in freq else 1
        neg[r["word2"]][r["word1"]] = freq[r["word1"]] if r["word1"] in freq else 1


    # merge pos and neg
    w_skipped = 0
    rel_num = 0
    pos_skipped = 0
    res = defaultdict(dict)
    for i, w1 in enumerate(pos):
        if w1 not in neg:
            print w1, "is missing in neg"
            w_skipped += 1
            continue
        else:
            rlen = min(len(pos[w1]), len(neg[w1]))
            if len(pos[w1]) > len(neg[w1]):
                print w1, "skipping ", len(pos[w1]) - len(neg[w1]), "of", len(pos[w1]), "positives"
                pos_skipped += len(pos[w1]) - len(neg[w1])
            if rlen < 1: 
                print w1, "has no relations"
                w_skipped += 1
                continue
            pos_lst = sorted(pos[w1], key=pos[w1].get, reverse=True)
            neg_lst = sorted(neg[w1], key=neg[w1].get, reverse=True) 
            for i in range(rlen):
                res[w1][pos_lst[i]] = 1
                res[w1][neg_lst[i]] = 0
                rel_num += 2

    with codecs.open(output_fpath, "w", "utf-8") as output:
        for x in res:
            for y in sorted(res[x], key=res[x].get, reverse=True):
                print >> output, "%s,%s,%d" % (x, y, res[x][y])

    print "# relations:", rel_num
    print "# word skipped:", w_skipped
    print "# pos skipped:", pos_skipped
    print "output:", output_fpath
    

def generate_negatives(relations_fpath, freq_fpath, pmi_w1_fpath, pmi_fpath, mult_coeff=MULT_COEFF):
    print "relations:", relations_fpath
    print "freq dictionary:", freq_fpath
    print "pmi w1:", pmi_w1_fpath
    print "pmi:", pmi_fpath
    print "multiplication coefficient:", mult_coeff

    tic = time()

    output_fpath = splitext(relations_fpath)[0] +  "-mc" + str(mult_coeff) + "-out.csv"
    common_fpath = splitext(relations_fpath)[0] + "-common.csv"
    freq_pkl_fpath = freq_fpath + ".pkl"

    pos_df = read_csv(relations_fpath, ',', encoding='utf8')
    rel_freq = Counter([w for w in pos_df.word1])

    if exists(freq_pkl_fpath):
        print "loading frequency dictionary from:", freq_pkl_fpath
        freq = pickle.load(open(freq_pkl_fpath, "rb"))
    else:
        print "building frequency dictionary from:", freq_fpath
        freq_df = read_csv(freq_fpath, '\t', encoding='utf8')
        freq = {row["word"]: row["freq"] for i, row in freq_df.iterrows()}
        pickle.dump(freq, open(freq_pkl_fpath, "wb"))
        print "frequency dictionary saved to:", freq_pkl_fpath

    w1_df = read_csv(pmi_w1_fpath, ',', encoding='utf8')
    w1_pmi = {w for w in w1_df.word}

    w1_rel = set(rel_freq.keys())
    common = w1_rel.intersection(w1_pmi)
    print "w1 total:", len(w1_rel)
    print "w1 found:", len(common)

    # save common relations and load them
    idx2del = []
    for i, row in pos_df.iterrows():
        if row.word1 not in common: idx2del.append(i)

    common_df = pos_df.copy()
    common_df.drop(idx2del)
    common_df.to_csv(common_fpath, delimiter=";", encoding="utf-8", index=False)

    positives = defaultdict(list)
    for w1, rows in common_df.groupby(["word1"]):
        for i, row in rows.iterrows(): positives[w1].append(row.word2)


    # find all related words
    with codecs.open(output_fpath, "w", "utf-8") as out:
        used_words = {}
        out.write("word1;word2;sim;freq\n")
        w1_prev = ""
        rels = []
        for i, line in enumerate(gzip.open(pmi_fpath, "rb")):
            if i % 1000000 == 0: print i / 1000000

            # is entry good?
            f = line.split("\t")
            w1 = f[0].decode("utf-8")
            if len(f) < 3 or w1 not in common: continue
            sim = float(f[2])
            w2 = f[1].decode("utf-8")
            if sim > MAX_PMI or w2 not in freq: continue
            pos = get_pos(w2)[0]
            if pos != "S" or len(w2) < MIN_LEN or w2 in used_words: continue

            # good entry
            if w1 != w1_prev and w1_prev != "":
                print ".",      
                r = {(w,s): freq[w] for w, s in rels}
                i = 0
                rnd_num = mult_coeff * rel_freq[w1_prev]
                for w, s in sorted(r, key=r.get, reverse=True):
                    out.write("%s;%s;%s;%s\n" % (w1_prev, w, s, freq[w]))
                    used_words[w] = 1
                    i += 1
                    if i >= rnd_num: break
                rels = [(w2, sim)]
            else:
                rels.append((w2, sim))

            w1_prev = w1

    print "elapsed: %d sec." % (time() - tic)
    

# Generate negatives like this:
"""   
dir_fpath = "/home/sasha/tmp/russe"
freq_fpath = join(dir_fpath, "freq.csv")
pmi_w1_fpath = join(dir_fpath, "w1-pmi.csv")
pmi_fpath = join(dir_fpath, "pmi.csv.gz")

for f in ["rt-train.csv","ae-train.csv", "ae2-train.csv"]:
    generate_negatives(join(dir_fpath, f), freq_fpath, pmi_w1_fpath, pmi_fpath, mult_coeff=1.5)

for f in ["rt-train.csv","ae-train.csv", "ae2-train.csv"]:
    generate_negatives(join(dir_fpath, f), freq_fpath, pmi_w1_fpath, pmi_fpath, mult_coeff=2)

for f in ["rt-train.csv","ae-train.csv", "ae2-train.csv"]:
    generate_negatives(join(dir_fpath, f), freq_fpath, pmi_w1_fpath, pmi_fpath, mult_coeff=1)
"""

# Merge positives and negatives like this:
"""
neg_fpath = "/home/sasha/russe/data/release/test/neg0.csv"
freq_fpath = "/home/sasha/russe/data/freq/wiki-freq-short3.csv"

pos_fpath = "/home/sasha/russe/data/release/test/ae-test.csv"
merge_pos_and_neg(pos_fpath, neg_fpath, freq_fpath)

pos_fpath = "/home/sasha/russe/data/release/test/ae2-test.csv"
merge_pos_and_neg(pos_fpath, neg_fpath, freq_fpath)

pos_fpath = "/home/sasha/russe/data/release/test/rt-test.csv"
merge_pos_and_neg(pos_fpath, neg_fpath, freq_fpath)
"""
