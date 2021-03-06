from data import *
from utils.augmentations import SSDAugmentation
import os
import sys
import time
import random
import tools
import torch
import torch.nn as nn
import torch.optim as optim
import torch.backends.cudnn as cudnn
import torch.nn.init as init
import torch.utils.data as data
import numpy as np
import matplotlib.pyplot as plt
import argparse

import torchvision.transforms as TF

parser = argparse.ArgumentParser(description='YOLO-v1 Detection')
parser.add_argument('-v', '--version', default='yolo_v1',
                    help='yolo_v1, yolo_anchor, yolo_v1_ms')
parser.add_argument('-d', '--dataset', default='VOC',
                    help='VOC or COCO dataset')
parser.add_argument('-bk', '--backbone', type=str, default='r18',
                    help='r18, r50, d19')
parser.add_argument('-hr', '--high_resolution', type=int, default=0,
                    help='0: use high resolution to pretrain; 1: else not.')                    
parser.add_argument('-fl', '--use_focal', type=int, default=0,
                    help='0: use focal loss; 1: else not;')
parser.add_argument('--batch_size', default=64, type=int, 
                    help='Batch size for training')
parser.add_argument('--lr', default=1e-3, type=int, 
                    help='initial learning rate')
parser.add_argument('-wp', '--warm_up', type=str, default='yes',
                    help='yes or no to choose using warmup strategy to train')
parser.add_argument('--wp_epoch', type=int, default=6,
                    help='The upper bound of warm-up')
parser.add_argument('--dataset_root', default=VOC_ROOT, 
                    help='Location of VOC root directory')
parser.add_argument('--num_classes', default=20, type=int, 
                    help='The number of dataset classes')
parser.add_argument('--momentum', default=0.9, type=float, 
                    help='Momentum value for optim')
parser.add_argument('--weight_decay', default=5e-4, type=float, 
                    help='Weight decay for SGD')
parser.add_argument('--gamma', default=0.1, type=float, 
                    help='Gamma update for SGD')
parser.add_argument('--num_workers', default=8, type=int, 
                    help='Number of workers used in dataloading')
parser.add_argument('--gpu_ind', default=0, type=int, 
                    help='To choose your gpu.')
parser.add_argument('--save_folder', default='weights/', type=str, 
                    help='Gamma update for SGD')

args = parser.parse_args()



def setup_seed(seed):
     torch.manual_seed(seed)
     torch.cuda.manual_seed_all(seed)
     np.random.seed(seed)
     random.seed(seed)
     torch.backends.cudnn.deterministic = True

# setup_seed(20)
def get_device():
    if torch.cuda.is_available():
        print('Let us use GPU to train')
        cudnn.benchmark = True
        if torch.cuda.device_count() == 1:
            device = torch.device('cuda')
        else:
            device = torch.device('cuda:%d' % args.gpu_ind)
    else:
        print('Come on !! No GPU ?? Who gives you the courage to study Deep Learning ?')
        device = torch.device('cpu')

    return device

def train(model):
    global cfg, hr, use_anchor

    # set GPU
    if not os.path.exists(args.save_folder):
        os.mkdir(args.save_folder)
    device = get_device()

    use_focal = False
    if args.use_focal == 1:
        print("Let's use focal loss for objectness !!!")
        use_focal = True


    dataset = VOCDetection(root=args.dataset_root,
                            transform=SSDAugmentation(cfg['min_dim'],
                                                        MEANS))

    from torch.utils.tensorboard import SummaryWriter
    log_path = 'log/'
    if not os.path.exists(log_path):
        os.mkdir(log_path)

    writer = SummaryWriter(log_path)
    
    print("----------------------------------------Object Detection--------------------------------------------")
    print("Let's train OD network !")
    net = model
    net = net.to(device)

    # optimizer = optim.Adam(net.parameters())
    optimizer = optim.SGD(net.parameters(), lr=args.lr, momentum=args.momentum,
                                            weight_decay=args.weight_decay)

    # loss counters
    print('Loading the dataset...')
    print('Training on:', dataset.name)
    print('The dataset size:', len(dataset))

    step_index = 0
    epoch_size = len(dataset) // args.batch_size
    # each part of loss weight
    obj_w = 1.0
    cla_w = 1.0
    box_w = 5.0

    data_loader = data.DataLoader(dataset, args.batch_size,
                                  num_workers=args.num_workers,
                                  shuffle=True, collate_fn=detection_collate,
                                  pin_memory=True)
    # create batch iterator
    iteration = 0

    # start training
    for epoch in range(cfg['max_epoch']):
        batch_iterator = iter(data_loader)
        
        # No WarmUp strategy or WarmUp tage has finished.
        if epoch in cfg['lr_epoch']:
            step_index += 1
            adjust_learning_rate(optimizer, args.gamma, step_index)

        for images, targets in batch_iterator:
            # WarmUp strategy for learning rate
            if args.warm_up == 'yes':
                if epoch < args.wp_epoch:
                    warmup_strategy(optimizer, args.gamma, epoch, epoch_size, iteration)
            iteration += 1
            # load train data
            # images, targets = next(batch_iterator)
            targets = [label.tolist() for label in targets]
            if args.version == 'yolo_v1_ms':
                targets = tools.multi_gt_creator(input_size=cfg['min_dim'], strides=yolo_net.stride, scale_thresholds=cfg['scale_thresh'], 
                                                 num_classes=args.num_classes, label_lists=targets, use_anchor=use_anchor)
            elif args.version == 'yolo_anchor_ms':
                targets = tools.multi_gt_creator(input_size=cfg['min_dim'], strides=yolo_net.stride, scale_thresholds=None,
                                                 num_classes=args.num_classes, label_lists=targets, use_anchor=use_anchor)
            else:
                targets = tools.gt_creator(cfg['min_dim'], yolo_net.stride, args.num_classes, targets, use_anchor=use_anchor)
            
            targets = torch.tensor(targets).float().to(device)

            # forward
            t0 = time.time()
            out = net(images.to(device))
            
            optimizer.zero_grad()
            
            obj_loss, class_loss, box_loss = tools.loss(out, targets, args.num_classes, use_anchor=use_anchor, use_focal=use_focal)
            # print(obj_loss.item(), class_loss.item(), box_loss.item())
            total_loss = obj_w * obj_loss + cla_w * class_loss + box_w * box_loss
            # viz loss
            writer.add_scalar('object loss', obj_loss.item(), iteration)
            writer.add_scalar('class loss', class_loss.item(), iteration)
            writer.add_scalar('local loss', box_loss.item(), iteration)
            # backprop
            total_loss.backward()
            optimizer.step()
            t1 = time.time()

            if iteration % 10 == 0:
                print('timer: %.4f sec.' % (t1 - t0))
                print('iter ' + repr(iteration) + ' || Loss: %.4f ||' % (total_loss.item()) + ' || lr: %.8f ||' % (lr), end=' ')

        if (epoch + 1) % 10 == 0:
            print('Saving state, epoch:', epoch + 1)
            torch.save(yolo_net.state_dict(), args.save_folder+ '/' + args.version + '_' +
                    repr(epoch + 1) + '.pth')


def adjust_learning_rate(optimizer, gamma, step_index):
    global lr
    """Sets the learning rate to the initial LR decayed by 10 at every
        specified step
    # Adapted from PyTorch Imagenet example:
    # https://github.com/pytorch/examples/blob/master/imagenet/main.py
    """
    lr = args.lr * (gamma ** (step_index))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr

def warmup_strategy(optimizer, gamma, epoch, epoch_size, iteration):
    global lr
    lr = 1e-6 + (args.lr-1e-6) * iteration / (epoch_size * (args.wp_epoch)) 
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr

if __name__ == '__main__':
    global hr, cfg, use_anchor

    hr = False
    use_anchor = False
    device = get_device()
    
    if args.high_resolution == 1:
        hr = True

    if args.version == 'yolo_v1':
        from models.yolo_v1 import myYOLOv1
        cfg = voc_af
        
        yolo_net = myYOLOv1(device, input_size=cfg['min_dim'], num_classes=args.num_classes, trainable=True, hr=hr, backbone=args.backbone)
        print('Let us train yolo-v1 on the VOC0712 dataset ......')
    
    elif args.version == 'yolo_anchor':
        from models.yolo_anchor import myYOLOv1
        cfg = voc_ab
        use_anchor = True
        total_anchor_size = tools.get_total_anchor_size(cfg['min_dim'], cfg['stride'])
        
        yolo_net = myYOLOv1(device, input_size=cfg['min_dim'], num_classes=args.num_classes, trainable=True, anchor_size=total_anchor_size, hr=hr, backbone=args.backbone)
        print('Let us train yolo-anchor on the VOC0712 dataset ......')
     
    elif args.version == 'yolo_v1_ms':
        from models.yolo_v1_ms import myYOLOv1
        cfg = voc_af
        
        yolo_net = myYOLOv1(device, input_size=cfg['min_dim'], num_classes=args.num_classes, trainable=True, hr=hr, backbone=args.backbone)
        print('Let us train yolo-v1-ms on the VOC0712 dataset ......')
        
    else:
        print('Unknown Version !!!')
        exit()
    
    train(yolo_net)