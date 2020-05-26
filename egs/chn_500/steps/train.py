'''
Copyright 2018-2019 Tsinghua University, Author: Hongyu Xiang 
Apache 2.0.
This script shows how to excute CTC-CRF neural network training with PyTorch.
'''
from ctc_crf import CTC_CRF_LOSS
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import torch.nn.functional as F
from torch.autograd import Variable
import numpy as np
import timeit
import os
import sys
import argparse
from torch.autograd import Function
import gc
from torch.utils.data import Dataset, DataLoader
from model import BLSTM
from dataset import SpeechDataset, SpeechDatasetMem, PadCollate
from prefetch_generator import BackgroundGenerator
import argparse
sys.path.append('../../src/ctc_crf')
import ctc_crf_base


os.environ['CUDA_VISIBLE_DEVICES'] = '0,1,2,3'
TARGET_GPUS = [0, 1, 2, 3]
gpus = torch.IntTensor(TARGET_GPUS)
ctc_crf_base.init_env('data/den_meta/den_lm.fst', gpus)

os.system("mkdir -p models")

class Model(nn.Module):
    def __init__(self, idim, hdim,  K, n_layers, dropout, lamb):
        super(Model, self).__init__()
        self.net = BLSTM(idim,  hdim, n_layers, dropout=0.5)
        self.linear = nn.Linear(hdim*2, K)
        self.loss_fn = CTC_CRF_LOSS( lamb=lamb )

    def forward(self, logits, labels_padded, input_lengths, label_lengths):
        # rearrange by input_lengths
        input_lengths, indices = torch.sort(input_lengths, descending=True)
        assert indices.dim()==1, "input_lengths should have only 1 dim"
        logits = torch.index_select(logits, 0, indices)
        labels_padded = torch.index_select(labels_padded, 0, indices)
        label_lengths = torch.index_select(label_lengths, 0, indices)

        labels_padded = labels_padded.cpu()
        input_lengths = input_lengths.cpu()
        label_lengths = label_lengths.cpu()

        label_list = [labels_padded[i, :x] for i,x in enumerate(label_lengths)]
        labels = torch.cat(label_list)
        netout, _ = self.net(logits, input_lengths)
        netout = self.linear(netout)
        netout = F.log_softmax(netout, dim=2)

        loss = self.loss_fn(netout, labels, input_lengths, label_lengths)
        return loss

def adjust_lr(optimizer, lr):
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr

def train():
    parser = argparse.ArgumentParser(description="recognition argument")
    parser.add_argument("--min_epoch", type=int, default=15)
    parser.add_argument("--output_unit", type=int)
    parser.add_argument("--lamb", type=float,default=0.1)
    parser.add_argument("--hdim",type=int,default=512)
    parser.add_argument("--layers",type=int,default=6)
    parser.add_argument("--dropout",type=int,default=0.5)
    parser.add_argument("--feature_size",type=int,default=120)
    parser.add_argument("--data_path")
    args = parser.parse_args()
    
    batch_size = 128
    
    model = Model(args.feature_size, args.hdim, args.output_unit, args.layers, args.dropout,args.lamb)
    device = torch.device("cuda:0")
    model.cuda()
    if torch.cuda.device_count() > 1:
        model = nn.DataParallel(model)
    model.to(device)
    #model.load_state_dict(torch.load(args.data_path+"/models/best_model"))
    #torch.backends.cudnn.enabled = False
    lr = 0.001
    optimizer = optim.Adam(model.parameters(), lr=lr)
    print ("Loading training data....")
    tr_dataset = SpeechDataset("/data/disk2/yuanrong/data_chn2000/data/tr.hdf5")
    #tr_dataset = SpeechDataset(args.data_path+"/data/hdf5/tr.hdf5")
    tr_dataloader = DataLoader(tr_dataset, batch_size=batch_size, shuffle=False, num_workers=24, collate_fn=PadCollate())
    print ("Loading cross validation data....")
    cv_dataset = SpeechDataset("/data/disk2/yuanrong/data_chn2000/data/cv.hdf5")
    #cv_dataset = SpeechDataset(args.data_path+"/data/hdf5/cv.hdf5")
    cv_dataloader = DataLoader(cv_dataset, batch_size=batch_size, shuffle=False, num_workers=16, collate_fn=PadCollate())

    prev_t = 0
    epoch = 0
    prev_cv_loss = np.inf
    tr_loss = 0
    model.train()
    print ("start training....")
    while True:
        # training stage
        #torch.save(model.module.state_dict(), args.data_path+"/models/best_model")
        epoch += 1
        gc.collect()
        for i, minibatch in enumerate(tr_dataloader):
            print("training epoch: {}, step: {}".format(epoch, i))
            logits, input_lengths, labels_padded, label_lengths, path_weights = minibatch
            if (logits.size(0) < 16):
                continue

            sys.stdout.flush()
            model.zero_grad()
            optimizer.zero_grad()

            loss = model(logits, labels_padded, input_lengths, label_lengths)
            partial_loss = torch.mean(loss.cpu())
            weight = torch.mean(path_weights)
            real_loss = partial_loss - weight
            loss.backward(torch.ones_like(loss))
            #loss.backward(loss.new_ones(8))
            tr_loss = real_loss.item()
            optimizer.step()
            t2 = timeit.default_timer()
            print("time: {}, tr_real_loss: {}, lr: {}".format(t2 - prev_t, real_loss.item(), optimizer.param_groups[0]['lr']))
            prev_t = t2
       
        # save model
        #torch.save(model.module.state_dict(), args.data_path+"/models/model.epoch.{}".format(epoch))

        # cv stage
        model.eval()
        cv_losses = []
        for i, minibatch in enumerate(cv_dataloader):
            print("cv epoch: {}, step: {}".format(epoch, i))
            logits, input_lengths, labels_padded, label_lengths, path_weights = minibatch
            if (logits.size(0) < 16):
                continue
            loss = model(logits, labels_padded, input_lengths, label_lengths)
            partial_loss = torch.mean(loss.cpu())
            weight = torch.mean(path_weights)
            real_loss = partial_loss - weight
            cv_losses.append(real_loss.item())
            print("cv_real_loss: {}".format(real_loss.item()))

        cv_loss = np.mean(np.asarray(cv_losses))
        print("mean_cv_loss: {}".format(cv_loss))
        if epoch < args.min_epoch or cv_loss <= prev_cv_loss:
            torch.save(model.module.state_dict(), args.data_path+"/models/model.epoch.{}_tr{}_cv{}".format(epoch, tr_loss, cv_loss))
            torch.save(model.module.state_dict(),args.data_path+ "/models/best_model")
            prev_cv_loss = cv_loss
        else:
            torch.save(model.module.state_dict(), args.data_path+"/models/model.epoch.{}_tr{}_cv{}_rejected".format(epoch, tr_loss, cv_loss))
            print("cv loss does not improve, decay the learning rate from {} to {}".format(lr, lr / 10.0))
            adjust_lr(optimizer, lr / 10.0)
            lr = lr / 10.0
            if (lr < 0.00001):
                print("lr is too slow, finish training")
                break

        model.train()

    ctc_crf_base.release_env(gpus)

if __name__ == "__main__":
     train()
