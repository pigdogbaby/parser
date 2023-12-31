# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import List, Tuple

import torch
import torch.nn as nn
from supar.utils.fn import pad
from supar.utils.tokenizer import TransformerTokenizer
from .modeling_roberta import RobertaModel

class TransformerEmbedding(nn.Module):
    r"""
    Bidirectional transformer embeddings of words from various transformer architectures :cite:`devlin-etal-2019-bert`.

    Args:
        name (str):
            Path or name of the pretrained models registered in `transformers`_, e.g., ``'bert-base-cased'``.
        n_layers (int):
            The number of BERT layers to use. If 0, uses all layers.
        n_out (int):
            The requested size of the embeddings. If 0, uses the size of the pretrained embedding model. Default: 0.
        stride (int):
            A sequence longer than max length will be splitted into several small pieces
            with a window size of ``stride``. Default: 10.
        pooling (str):
            Pooling way to get from token piece embeddings to token embedding.
            ``first``: take the first subtoken.
            ``last``: take the last subtoken.
            ``mean``: take a mean over all.
            ``None``: no reduction applied.
            Default: ``mean``.
        pad_index (int):
            The index of the padding token in BERT vocabulary. Default: 0.
        mix_dropout (float):
            The dropout ratio of BERT layers. This value will be passed into the :class:`ScalarMix` layer. Default: 0.
        finetune (bool):
            If ``True``, the model parameters will be updated together with the downstream task. Default: ``False``.

    .. _transformers:
        https://github.com/huggingface/transformers
    """

    def __init__(
        self,
        name: str,
        n_layers: int,
        n_out: int = 0,
        stride: int = 256,
        pooling: str = 'mean',
        pad_index: int = 0,
        mix_dropout: float = .0,
        rank: int = 64,
        finetune: bool = False,
        relation: bool = False,
        cpd: bool = False,
        softmax_head: bool = False,
        concate: bool = False
    ) -> TransformerEmbedding:
        super().__init__()

        from transformers import AutoConfig
        if concate:
            try:
                self.model = RobertaModel.from_pretrained(name, local_files_only=True)
            except Exception:
                self.model = RobertaModel.from_pretrained(name, local_files_only=False)
            self.model = self.model.requires_grad_(finetune)
            config = AutoConfig.from_pretrained(f"/home/wuyou/parser/{name}.json", output_hidden_states=True, output_attentions=relation)
            self.encoder = RobertaModel(config, custom=True, rank=rank, cpd=cpd, softmax_head=softmax_head, concate=True)
        else:
            if finetune:
                try:
                    self.model = RobertaModel.from_pretrained(name, output_hidden_states=True, output_attentions=relation, local_files_only=True)
                except Exception:
                    self.model = RobertaModel.from_pretrained(name, output_hidden_states=True, output_attentions=relation, local_files_only=False)
            else:
                config = AutoConfig.from_pretrained(f"/home/wuyou/parser/{name}.json", output_hidden_states=True, output_attentions=relation)
                self.model = RobertaModel(config, custom=True, rank=rank, cpd=cpd, softmax_head=softmax_head)
            self.model = self.model.requires_grad_(True)
        self.tokenizer = TransformerTokenizer(name)

        self.name = name
        self.n_layers = n_layers or self.model.config.num_hidden_layers
        self.hidden_size = self.encoder.config.hidden_size if concate else self.model.config.hidden_size
        self.rank = rank if cpd else self.encoder.config.num_attention_heads if concate else self.model.config.num_attention_heads
        self.n_out = n_out or self.hidden_size
        self.pooling = pooling
        self.pad_index = pad_index
        self.mix_dropout = mix_dropout
        self.finetune = finetune
        self.max_len = int(max(0, self.model.config.max_position_embeddings) or 1e12) - 2
        self.stride = min(stride, self.max_len)

        self.scalar_mix = ScalarMix(self.n_layers, mix_dropout)
        self.relation = relation
        self.cpd = cpd
        self.softmax_head = softmax_head
        self.concate = concate
        
    def __repr__(self):
        s = f"{self.name}"
        if self.n_layers > 1:
            s += f", n_layers={self.n_layers}"
        s += f", n_out={self.n_out}, stride={self.stride}"
        if self.pooling:
            s += f", pooling={self.pooling}"
        s += f", pad_index={self.pad_index}"
        if self.mix_dropout > 0:
            s += f", mix_dropout={self.mix_dropout}"
        if self.finetune:
            s += f", finetune={self.finetune}"
        return f"{self.__class__.__name__}({s})"

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        r"""
        Args:
            tokens (~torch.Tensor): ``[batch_size, seq_len, fix_len]``.

        Returns:
            ~torch.Tensor:
                Contextualized token embeddings of shape ``[batch_size, seq_len, n_out]``.
        """

        # print(tokens.shape)
        # torch.Size([35, 15, 4])
        # for i in range(tokens.shape[1]):
        #     print(tokens[i])
        # tensor([[   0,    1,    1,    1],
        # [  83,    1,    1,    1],
        # [ 812,   12,  571, 5069],
        # [ 629,    1,    1,    1],
        # [ 847,    1,    1,    1],
        # [ 563,    1,    1,    1],
        # [  34,    1,    1,    1],
        # [  57,    1,    1,    1],
        # [1006,    1,    1,    1],
        # [  66,    1,    1,    1],
        # [  30,    1,    1,    1],
        # [1112,    1,    1,    1],
        # [1858,    1,    1,    1],
        # [ 479,    1,    1,    1],
        # [   1,    1,    1,    1]], device='cuda:0')
        mask = tokens.ne(self.pad_index)
        lens = mask.sum((1, 2))
        # [batch_size, n_tokens]
        tokens = pad(tokens[mask].split(lens.tolist()), self.pad_index, padding_side=self.tokenizer.padding_side)
        # print(tokens.shape)
        # torch.Size([35, 22])
        # for i in range(tokens.shape[1]):
        #     print(tokens[i])
        # tensor([   0,   83,  812,   12,  571, 5069,  629,  847,  563,   34,   57, 1006,
        #         66,   30, 1112, 1858,  479,    1,    1,    1,    1,    1],
        #     device='cuda:0')
        token_mask = pad(mask[mask].split(lens.tolist()), 0, padding_side=self.tokenizer.padding_side)

        # return the hidden states of all layers
        x = self.model(tokens[:, :self.max_len], attention_mask=token_mask[:, :self.max_len].float())
        if self.concate:
            x = self.encoder(x.last_hidden_state, attention_mask=token_mask[:, :self.max_len].float())
        # if x.last_hidden_state is not None:
        #     print("last_hidden_state")
        #     print(x.last_hidden_state.shape)
        #     torch.Size([35, 22, 1024])
        # if x.pooler_output is not None:
        #     print("pooler_output")
        #     print(x.pooler_output.shape)
        #     torch.Size([35, 22])
        # if x.hidden_states is not None:
        #     print("hidden_states")
        #     for i in x.hidden_states:
        #         print(i.shape)
        #         torch.Size([35, 22, 1024])
        # if x.attentions is not None:
        #     print("attentions")
        #     for i in x.attentions:
        #         print(i.shape)
        #         torch.Size([35, 16, 22, 22])
        if self.relation:
            x = x.attentions
            # [batch_size, max_len, max_len, rank]
            x = self.scalar_mix(x[-self.n_layers:]).permute(0, 2, 3, 1)
        else:
            x = x.hidden_states
            # [batch_size, max_len, hidden_size]
            x = self.scalar_mix(x[-self.n_layers:])
            # [batch_size, n_tokens, hidden_size]
            for i in range(self.stride, (tokens.shape[1]-self.max_len+self.stride-1)//self.stride*self.stride+1, self.stride):
                part = self.model(tokens[:, i:i+self.max_len], attention_mask=token_mask[:, i:i+self.max_len].float())[-1]
                x = torch.cat((x, self.scalar_mix(part[-self.n_layers:])[:, self.max_len-self.stride:]), 1)
        # [batch_size, seq_len]
        lens = mask.sum(-1)
        # the length of each token, padding token is 0, now replace 0 with 1 to avoid divide 0 exception
        lens = lens.masked_fill_(lens.eq(0), 1)
        if self.relation:
            mask = torch.einsum('bim,bjn->bimjn', [mask, mask])
            token_mask = torch.einsum('bi,bj->bij', [token_mask, token_mask])
            # [batch_size, seq_len, fix_len, seq_len, fix_len, rank]
            x = x.new_zeros(*mask.shape, self.rank).masked_scatter_(mask.unsqueeze(-1), x[token_mask])
            if self.pooling == 'first':
                x = x[:, :, 0, :, 0]
            elif self.pooling == 'mean':
                lens = torch.einsum('bi,bj->bij', [lens, lens])
                x = x.sum((2, 4)) / lens.unsqueeze(-1)
            elif self.pooling:
                raise RuntimeError(f'Unsupported pooling method "{self.pooling}"!')
        else:
            # [batch_size, seq_len, fix_len, hidden_size]
            # x[token_mask]: [tot_len (< batch_size * seq_len), hidden_size]
            x = x.new_zeros(*mask.shape, self.hidden_size).masked_scatter_(mask.unsqueeze(-1), x[token_mask])
            # [batch_size, seq_len, hidden_size]
            if self.pooling == 'first':
                x = x[:, :, 0]
            elif self.pooling == 'last':
                x = x.gather(2, (lens-1).unsqueeze(-1).repeat(1, 1, self.hidden_size).unsqueeze(2)).squeeze(2)
            elif self.pooling == 'mean':
                x = x.sum(2) / lens.unsqueeze(-1)
            elif self.pooling:
                raise RuntimeError(f'Unsupported pooling method "{self.pooling}"!')
        return x


class ELMoEmbedding(nn.Module):
    r"""
    Contextual word embeddings using word-level bidirectional LM :cite:`peters-etal-2018-deep`.

    Args:
        name (str):
            The name of the pretrained ELMo registered in `OPTION` and `WEIGHT`. Default: ``'original_5b'``.
        bos_eos (Tuple[bool]):
            A tuple of two boolean values indicating whether to keep start/end boundaries of sentence outputs.
            Default: ``(True, True)``.
        n_out (int):
            The requested size of the embeddings. If 0, uses the default size of ELMo outputs. Default: 0.
        dropout (float):
            The dropout ratio for the ELMo layer. Default: 0.
        finetune (bool):
            If ``True``, the model parameters will be updated together with the downstream task. Default: ``False``.
    """

    OPTION = {
        'small': 'https://s3-us-west-2.amazonaws.com/allennlp/models/elmo/2x1024_128_2048cnn_1xhighway/elmo_2x1024_128_2048cnn_1xhighway_options.json',  # noqa
        'medium': 'https://s3-us-west-2.amazonaws.com/allennlp/models/elmo/2x2048_256_2048cnn_1xhighway/elmo_2x2048_256_2048cnn_1xhighway_options.json',  # noqa
        'original': 'https://s3-us-west-2.amazonaws.com/allennlp/models/elmo/2x4096_512_2048cnn_2xhighway/elmo_2x4096_512_2048cnn_2xhighway_options.json',  # noqa
        'original_5b': 'https://s3-us-west-2.amazonaws.com/allennlp/models/elmo/2x4096_512_2048cnn_2xhighway_5.5B/elmo_2x4096_512_2048cnn_2xhighway_5.5B_options.json',  # noqa
    }
    WEIGHT = {
        'small': 'https://s3-us-west-2.amazonaws.com/allennlp/models/elmo/2x1024_128_2048cnn_1xhighway/elmo_2x1024_128_2048cnn_1xhighway_weights.hdf5',  # noqa
        'medium': 'https://s3-us-west-2.amazonaws.com/allennlp/models/elmo/2x2048_256_2048cnn_1xhighway/elmo_2x2048_256_2048cnn_1xhighway_weights.hdf5',  # noqa
        'original': 'https://s3-us-west-2.amazonaws.com/allennlp/models/elmo/2x4096_512_2048cnn_2xhighway/elmo_2x4096_512_2048cnn_2xhighway_weights.hdf5',  # noqa
        'original_5b': 'https://s3-us-west-2.amazonaws.com/allennlp/models/elmo/2x4096_512_2048cnn_2xhighway_5.5B/elmo_2x4096_512_2048cnn_2xhighway_5.5B_weights.hdf5',  # noqa
    }

    def __init__(
        self,
        name: str = 'original_5b',
        bos_eos: Tuple[bool, bool] = (True, True),
        n_out: int = 0,
        dropout: float = 0.5,
        finetune: bool = False
    ) -> ELMoEmbedding:
        super().__init__()

        from allennlp.modules import Elmo

        self.elmo = Elmo(options_file=self.OPTION[name],
                         weight_file=self.WEIGHT[name],
                         num_output_representations=1,
                         dropout=dropout,
                         finetune=finetune,
                         keep_sentence_boundaries=True)

        self.name = name
        self.bos_eos = bos_eos
        self.hidden_size = self.elmo.get_output_dim()
        self.n_out = n_out or self.hidden_size
        self.dropout = dropout
        self.finetune = finetune

        self.projection = nn.Linear(self.hidden_size, self.n_out, False) if self.hidden_size != n_out else nn.Identity()

    def __repr__(self):
        s = f"{self.name}, n_out={self.n_out}"
        if self.dropout > 0:
            s += f", dropout={self.dropout}"
        if self.finetune:
            s += f", finetune={self.finetune}"
        return f"{self.__class__.__name__}({s})"

    def forward(self, chars: torch.LongTensor) -> torch.Tensor:
        r"""
        Args:
            chars (~torch.LongTensor): ``[batch_size, seq_len, fix_len]``.

        Returns:
            ~torch.Tensor:
                ELMo embeddings of shape ``[batch_size, seq_len, n_out]``.
        """

        x = self.projection(self.elmo(chars)['elmo_representations'][0])
        if not self.bos_eos[0]:
            x = x[:, 1:]
        if not self.bos_eos[1]:
            x = x[:, :-1]
        return x


class ScalarMix(nn.Module):
    r"""
    Computes a parameterized scalar mixture of :math:`N` tensors, :math:`mixture = \gamma * \sum_{k}(s_k * tensor_k)`
    where :math:`s = \mathrm{softmax}(w)`, with :math:`w` and :math:`\gamma` scalar parameters.

    Args:
        n_layers (int):
            The number of layers to be mixed, i.e., :math:`N`.
        dropout (float):
            The dropout ratio of the layer weights.
            If dropout > 0, then for each scalar weight, adjusts its softmax weight mass to 0
            with the dropout probability (i.e., setting the unnormalized weight to -inf).
            This effectively redistributes the dropped probability mass to all other weights.
            Default: 0.
    """

    def __init__(self, n_layers: int, dropout: float = .0) -> ScalarMix:
        super().__init__()

        self.n_layers = n_layers

        self.weights = nn.Parameter(torch.zeros(n_layers))
        self.gamma = nn.Parameter(torch.tensor([1.0]))
        self.dropout = nn.Dropout(dropout)

    def __repr__(self):
        s = f"n_layers={self.n_layers}"
        if self.dropout.p > 0:
            s += f", dropout={self.dropout.p}"
        return f"{self.__class__.__name__}({s})"

    def forward(self, tensors: List[torch.Tensor]) -> torch.Tensor:
        r"""
        Args:
            tensors (List[~torch.Tensor]):
                :math:`N` tensors to be mixed.

        Returns:
            The mixture of :math:`N` tensors.
        """

        return self.gamma * sum(w * h for w, h in zip(self.dropout(self.weights.softmax(-1)), tensors))
