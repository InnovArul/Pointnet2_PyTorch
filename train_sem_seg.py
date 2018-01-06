import torch
import torch.optim as optim
import torch.optim.lr_scheduler as lr_sched
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.utils.data.sampler import SubsetRandomSampler
from torch.autograd import Variable
import numpy as np
import tensorboard_logger as tb_log
import os

from models import Pointnet2SSG as Pointnet
from models.Pointnet2SemSeg import model_fn_decorator
from data import Indoor3DSemSeg
import utils.pytorch_utils as pt_utils

import argparse

parser = argparse.ArgumentParser(description="Arg parser")
parser.add_argument(
    "-batch_size", type=int, default=32, help="Batch size [default: 32]"
)
parser.add_argument(
    "-num_points",
    type=int,
    default=2048,
    help="Number of points to train with [default: 2048]"
)
parser.add_argument(
    "-weight_decay",
    type=float,
    default=0,
    help="L2 regularization coeff [default: 0.0]"
)
parser.add_argument(
    "-lr",
    type=float,
    default=1e-2,
    help="Initial learning rate [default: 1e-2]"
)
parser.add_argument(
    "-lr_decay",
    type=float,
    default=0.5,
    help="Learning rate decay gamma [default: 0.5]"
)
parser.add_argument(
    "-decay_step",
    type=int,
    default=20,
    help="Learning rate decay step [default: 20]"
)
parser.add_argument(
    "-bn_momentum",
    type=float,
    default=0.9,
    help="Initial batch norm momentum [default: 0.9]"
)
parser.add_argument(
    "-bn_decay",
    type=float,
    default=0.5,
    help="Batch norm momentum decay gamma [default: 0.5]"
)
parser.add_argument(
    "-checkpoint", type=str, default=None, help="Checkpoint to start from"
)
parser.add_argument(
    "-epochs", type=int, default=200, help="Number of epochs to train for"
)
parser.add_argument(
    "-run_name",
    type=str,
    default="sem_seg_run_1",
    help="Name for run in tensorboard_logger"
)

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

lr_clip = 1e-5
bnm_clip = 1e-2

if __name__ == "__main__":
    args = parser.parse_args()
    tb_log.configure('runs/{}'.format(args.run_name))

    test_set = Indoor3DSemSeg(
        args.num_points, BASE_DIR, train=False, data_precent=0.01
    )
    test_loader = DataLoader(
        test_set,
        batch_size=args.batch_size,
        shuffle=True,
        pin_memory=True,
        num_workers=2
    )

    train_set = Indoor3DSemSeg(args.num_points, BASE_DIR, data_precent=1.0)
    train_loader = DataLoader(
        train_set,
        batch_size=args.batch_size,
        pin_memory=True,
        num_workers=2,
        shuffle=True
    )

    model = Pointnet(num_classes=13)
    model.cuda()
    optimizer = optim.Adam(
        model.parameters(), lr=args.lr, weight_decay=args.weight_decay
    )

    lr_lbmd = lambda e: max(args.lr_decay**(e // args.decay_step), lr_clip / args.lr)
    bnm_lmbd = lambda e: max(args.bn_momentum * args.bn_decay**(e // args.decay_step), bnm_clip)

    if args.checkpoint is None:
        lr_scheduler = lr_sched.LambdaLR(optimizer, lr_lbmd)
        bnm_scheduler = pt_utils.BNMomentumScheduler(model, bnm_lmbd)
        start_epoch = 1
        best_prec = 0
        best_loss = 1e10
    else:
        start_epoch, best_loss = pt_utils.load_checkpoint(
            model, optimizer, filename=args.checkpoint.split(".")[0]
        )

        lr_scheduler = lr_sched.LambdaLR(
            optimizer, lr_lbmd, last_epoch=start_epoch
        )
        bnm_scheduler = pt_utils.BNMomentumScheduler(
            model, bnm_lmbd, last_epoch=start_epoch
        )

    model_fn = model_fn_decorator(nn.CrossEntropyLoss())

    trainer = pt_utils.Trainer(
        model,
        model_fn,
        optimizer,
        checkpoint_name="sem_seg_checkpoint",
        best_name="sem_seg_best",
        lr_scheduler=lr_scheduler,
        bnm_scheduler=bnm_scheduler,
        eval_frequency=10
    )

    trainer.train(
        start_epoch,
        args.epochs,
        train_loader,
        test_loader,
        best_loss=best_loss
    )

    if start_epoch == args.epochs:
        test_loader.dataset.data_precent = 1.0
        _ = trainer.eval_epoch(start_epoch, test_loader)
