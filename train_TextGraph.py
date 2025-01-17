import os
import gc
import time
from datetime import datetime
import torch
import numpy as np
import torch.nn as nn
import torch.backends.cudnn as cudnn
import torch.utils.data as data
from torch.optim import lr_scheduler

from dataset import SynthText, TotalText, Ctw1500Text, Icdar15Text, Mlt2017Text, TD500Text , VietSceneText, VinText
from network.loss import TextLoss
from network.textnet import TextNet
from util.augmentation import Augmentation
from util.config import config as cfg, update_config, print_config
from util.misc import AverageMeter
from util.misc import mkdirs, to_device
from util.option import BaseOptions
from util.visualize import visualize_network_output
from util.summary import LogSummary
from util.shedule import FixLR
# import multiprocessing
# multiprocessing.set_start_method("spawn", force=True)

import warnings
warnings.filterwarnings('ignore')

lr = None
train_step = 0

date = datetime.now().strftime("%H%M-%d%m%y")

def save_model(model, epoch, lr, optimzer):

    save_dir = os.path.join(cfg.save_dir, cfg.exp_name + date)
    if not os.path.exists(save_dir):
        mkdirs(save_dir)
    if cfg.mgpu:
        model_name = model.module.backbone_name
    else:
        model_name = model.backbone_name
    save_path = os.path.join(save_dir, 'textgraph_{}_{}.pth'.format(model_name , epoch))
    print('Saving to {}.'.format(save_path))
    state_dict = {
        'lr': lr,
        'epoch': epoch,
        'model': model.state_dict() if not cfg.mgpu else model.module.state_dict(),
        'optimizer': optimzer.state_dict()
    }
    torch.save(state_dict, save_path)


def load_model(model, model_path):
    print('Loading from {}'.format(model_path))
    state_dict = torch.load(model_path)
    model.load_state_dict(state_dict['model'])


def train(model, train_loader, criterion, scheduler, optimizer, epoch, logger):

    global train_step

    losses = AverageMeter()
    batch_time = AverageMeter()
    data_time = AverageMeter()
    end = time.time()
    model.train()
    # scheduler.step()

    print('Epoch: {} : LR = {}'.format(epoch, scheduler.get_lr()))

    for i, (img, train_mask, tr_mask, tcl_mask, radius_map, sin_map, cos_map, gt_roi) in enumerate(train_loader):
        data_time.update(time.time() - end)

        train_step += 1

        img, train_mask, tr_mask, tcl_mask, radius_map, sin_map, cos_map \
            = to_device(img, train_mask, tr_mask, tcl_mask, radius_map, sin_map, cos_map)

        output, gcn_data = model(img, gt_roi, to_device)

        tr_loss, tcl_loss, sin_loss, cos_loss, radii_loss, gcn_loss \
            = criterion(output, gcn_data, train_mask, tr_mask, tcl_mask, radius_map, sin_map, cos_map)
        loss = tr_loss + tcl_loss + sin_loss + cos_loss + radii_loss + gcn_loss

        # backward
        try:
            optimizer.zero_grad()
            loss.backward()
        except:
            print("loss gg")
            continue

        optimizer.step()

        losses.update(loss.item())
        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()
        gc.collect()

        if cfg.viz and i % cfg.viz_freq == 0:
            visualize_network_output(output, tr_mask, tcl_mask[:, :, :, 0], mode='train')

        if i % cfg.display_freq == 0:
            print('({:d} / {:d})  Loss: {:.4f}  tr_loss: {:.4f}  tcl_loss: {:.4f}  '
                  'sin_loss: {:.4f}  cos_loss: {:.4f}  radii_loss: {:.4f}  gcn_loss: {:.4f}'
                  .format(i, len(train_loader), loss.item(), tr_loss.item(), tcl_loss.item(),
                          sin_loss.item(), cos_loss.item(), radii_loss.item(), gcn_loss.item()))

        if i % cfg.log_freq == 0:
            logger.write_scalars({
                'loss': loss.item(),
                'tr_loss': tr_loss.item(),
                'tcl_loss': tcl_loss.item(),
                'sin_loss': sin_loss.item(),
                'cos_loss': cos_loss.item(),
                'radii_loss': radii_loss.item(),
                'gcn_loss:': gcn_loss.item()
            }, tag='train', n_iter=train_step)

    if epoch % cfg.save_freq == 0:
        save_model(model, epoch, scheduler.get_lr(), optimizer)

    print('Training Loss: {}'.format(losses.avg))


def main():

    global lr
    if cfg.exp_name == 'Totaltext':
        trainset = TotalText(
            data_root='data/total-text-mat',
            ignore_list=None,
            is_training=True,
            transform=Augmentation(size=cfg.input_size, mean=cfg.means, std=cfg.stds)
        )
        # valset = TotalText(
        #     data_root='data/total-text-mat',
        #     ignore_list=None,
        #     is_training=False,
        #     transform=BaseTransform(size=cfg.input_size, mean=cfg.means, std=cfg.stds)
        # )
        valset = None

    elif cfg.exp_name == 'Synthtext':
        trainset = SynthText(
            data_root='data/SynthText',
            is_training=True,
            transform=Augmentation(size=cfg.input_size, mean=cfg.means, std=cfg.stds)
        )
        valset = None

    elif cfg.exp_name == 'Ctw1500':
        trainset = Ctw1500Text(
            data_root='data/ctw1500',
            is_training=True,
            transform=Augmentation(size=cfg.input_size, mean=cfg.means, std=cfg.stds)
        )
        valset = None

    elif cfg.exp_name == 'Icdar2015':
        trainset = Icdar15Text(
            data_root='data/Icdar2015',
            is_training=True,
            transform=Augmentation(size=cfg.input_size, mean=cfg.means, std=cfg.stds)
        )
        valset = None
    elif cfg.exp_name == 'MLT2017':
        trainset = Mlt2017Text(
            data_root='data/MLT2017',
            is_training=True,
            transform=Augmentation(size=cfg.input_size, mean=cfg.means, std=cfg.stds)
        )
        valset = None

    elif cfg.exp_name == 'TD500':
        trainset = TD500Text(
            data_root='data/TD500',
            is_training=True,
            transform=Augmentation(size=cfg.input_size, mean=cfg.means, std=cfg.stds)
        )
        valset = None

    elif cfg.exp_name == 'VietSceneText':
        trainset = VietSceneText(
            data_root='data/VietSceneText',
            is_training=True,
            transform=Augmentation(size=cfg.input_size, mean=cfg.means, std=cfg.stds)
        )
        valset = None
    elif cfg.exp_name == 'VinText':
        trainset = VinText(
            data_root='data/VinText',
            is_training=True,
            transform=Augmentation(size=cfg.input_size, mean=cfg.means, std=cfg.stds)
        )
        valset = None
    else:
        print("dataset name is not correct")

    train_loader = data.DataLoader(trainset, batch_size=cfg.batch_size,
                                   shuffle=True, num_workers=cfg.num_workers, pin_memory=True)

    log_dir = os.path.join(cfg.log_dir, datetime.now().strftime('%b%d_%H-%M-%S_') + cfg.exp_name)
    logger = LogSummary(log_dir)

    # Model
    model = TextNet(backbone=cfg.net, is_training=True)
    if cfg.mgpu:
        model = nn.DataParallel(model)

    model = model.to(cfg.device)
    if cfg.cuda:
        cudnn.benchmark = True

    if cfg.resume:
        load_model(model, cfg.resume)

    criterion = TextLoss()

    lr = cfg.lr
    moment = cfg.momentum
    if cfg.optim == "Adam" or cfg.exp_name == 'Synthtext':
        optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    else:
        optimizer = torch.optim.SGD(model.parameters(), lr=lr, momentum=moment)

    if cfg.exp_name == 'Synthtext':
        scheduler = FixLR(optimizer)
    else:
        scheduler = lr_scheduler.StepLR(optimizer, step_size=100, gamma=0.90)

    print('Start training TextGraph.')
    for epoch in range(cfg.start_epoch, cfg.start_epoch + cfg.max_epoch+1):
        scheduler.step()
        train(model, train_loader, criterion, scheduler, optimizer, epoch, logger)

    print('End.')

    if torch.cuda.is_available():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    np.random.seed(2019)
    torch.manual_seed(2019)
    # parse arguments
    option = BaseOptions()
    args = option.initialize()

    update_config(cfg, args)
    print_config(cfg)

    # main
    main()

