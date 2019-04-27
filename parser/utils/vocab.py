# -*- coding: utf-8 -*-

from collections import Counter

import torch


class Vocab(object):
    PAD = '<PAD>'
    UNK = '<UNK>'

    def __init__(self, words, chars, rels):
        self.pad_index = 0
        self.unk_index = 1

        self.words = [self.PAD, self.UNK] + sorted(words)
        self.chars = [self.PAD, self.UNK] + sorted(chars)
        self.rels = sorted(rels)

        self.word_dict = {w: i for i, w in enumerate(self.words)}
        self.char_dict = {c: i for i, c in enumerate(self.chars)}
        self.rel_dict = {l: i for i, l in enumerate(self.rels)}

        self.n_words = len(self.words)
        self.n_chars = len(self.chars)
        self.n_rels = len(self.rels)
        self.n_train_words = self.n_words

    def __repr__(self):
        info = f"{self.__class__.__name__}(\n"
        info += f"  num of words: {self.n_words}\n"
        info += f"  num of chars: {self.n_chars}\n"
        info += f"  num of rels: {self.n_rels}\n"
        info += f")"

        return info

    def word2id(self, sequence):
        return torch.tensor([self.word_dict.get(word.lower(), self.unk_index)
                             for word in sequence])

    def char2id(self, sequence, fix_length=20):
        char_ids = torch.zeros(len(sequence), fix_length, dtype=torch.long)
        for i, word in enumerate(sequence):
            ids = torch.tensor([self.char_dict.get(c, self.unk_index)
                                for c in word[:fix_length]])
            char_ids[i, :len(ids)] = ids

        return char_ids

    def rel2id(self, sequence):
        return torch.tensor([self.rel_dict.get(rel, 0)
                             for rel in sequence])

    def id2rel(self, ids):
        return [self.rels[i] for i in ids]

    def read_embeddings(self, embed, unk=None):
        words = embed.words
        # if the UNK token has existed in pretrained vocab,
        # then replace it with a self-defined one
        if unk:
            words[words.index(unk)] = self.UNK

        self.extend(words)
        self.embeddings = torch.zeros(self.n_words, embed.dim)

        for i, word in enumerate(self.words):
            if word in embed:
                self.embeddings[i] = embed[word]
        self.embeddings /= torch.std(self.embeddings)

    def extend(self, words):
        self.words.extend(set(words).difference(self.word_dict))
        self.chars.extend(set(''.join(words)).difference(self.char_dict))
        self.word_dict = {w: i for i, w in enumerate(self.words)}
        self.char_dict = {c: i for i, c in enumerate(self.chars)}
        self.n_words = len(self.words)
        self.n_chars = len(self.chars)

    def numericalize(self, corpus):
        words = [self.word2id(seq) for seq in corpus.word_seqs]
        chars = [self.char2id(seq) for seq in corpus.word_seqs]
        arcs = [torch.tensor(seq) for seq in corpus.head_seqs]
        rels = [self.rel2id(seq) for seq in corpus.rel_seqs]

        return words, chars, arcs, rels

    @classmethod
    def from_corpus(cls, corpus, min_freq=1):
        words = Counter(word.lower() for word in corpus.words.elements())
        words = list(word for word, freq in words.items() if freq >= min_freq)
        chars = list({char for char in ''.join(corpus.words)})
        rels = list(corpus.rels)
        vocab = cls(words, chars, rels)

        return vocab