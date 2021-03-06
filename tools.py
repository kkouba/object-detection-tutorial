import numpy as np
from data import *
import torch.nn as nn
import torch.nn.functional as F

CLASS_COLOR = [(np.random.randint(255),np.random.randint(255),np.random.randint(255)) for _ in range(len(VOC_CLASSES))]
# We use ignore thresh to decide which anchor box can be kept.
ignore_thresh = IGNORE_THRESH

class BCELoss(nn.Module):
    def __init__(self,  weight=None, ignore_index=-100, reduce=None, reduction='mean'):
        super(BCELoss, self).__init__()
        self.reduction = reduction
    def forward(self, inputs, targets):
        pos_id = (targets==1.0).float()
        neg_id = (1 - pos_id).float()
        pos_loss = -pos_id * torch.log(inputs + 1e-14)
        neg_loss = -neg_id * torch.log(1.0 - inputs + 1e-14)
        pos_num = torch.sum(pos_id, 1)
        neg_num = torch.sum(neg_id, 1)
        if self.reduction == 'mean':
            pos_loss = torch.mean(torch.sum(pos_loss, 1))
            neg_loss = torch.mean(torch.sum(neg_loss, 1))
            return pos_loss, neg_loss
        else:
            return pos_loss, neg_loss

class BCE_focal_loss(nn.Module):
    def __init__(self,  weight=None, gamma=2, reduction='mean'):
        super(BCE_focal_loss, self).__init__()
        self.gamma = gamma
        self.reduction = reduction
    def forward(self, inputs, targets):
        pos_id = (targets==1.0).float()
        neg_id = (1 - pos_id).float()
        pos_loss = -pos_id * (1.0-inputs)**self.gamma * torch.log(inputs + 1e-14)
        neg_loss = -neg_id * (inputs)**self.gamma * torch.log(1.0 - inputs + 1e-14)

        if self.reduction == 'mean':
            return torch.mean(torch.sum(pos_loss+neg_loss, 1))
        else:
            return pos_loss+neg_loss
  
def generate_anchor(input_size, stride, anchor_scale, anchor_aspect):
    """
        The function is used to design anchor boxes by ourselves as long as you provide the scale and aspect of anchor boxes.
        Input:
            input_size : list -> the image resolution used in training stage and testing stage.
            stride : int -> the downSample of the CNN, such as 32, 64 and so on.
            anchor_scale : list -> it contains the area ratio of anchor boxes. For example, anchor_scale = [0.1, 0.5]
            anchor_aspect : list -> it contains the aspect ratios of anchor boxes for various anchor area.
                            For example, anchor_aspect = [[1.0, 2.0], [3.0, 1/3]]. And len(anchor_aspect) must 
                            be equal to len(anchor_scale).
        Output:
            total_anchor_size : list -> [[h_1, w_1], [h_2, w_2], ..., [h_n, w_n]].
    """
    assert len(anchor_scale) == len(anchor_aspect)
    h, w = input_size
    hs, ws = h // stride, w // stride
    S_fmap = hs * ws
    total_anchor_size = []
    for ab_scale, aspect_ratio in zip(anchor_scale, anchor_aspect):
        for a in aspect_ratio:
            S_ab = S_fmap * ab_scale
            ab_w = np.floor(np.sqrt(S_ab))
            ab_h =ab_w * a
            total_anchor_size.append([ab_w, ab_h])
    return total_anchor_size

def get_total_anchor_size(input_size, stride=None, multi_scale=False, name='VOC'):
    if multi_scale:
        all_anchor_size = MULTI_ANCHOR_SIZE
    else:
        if name == 'VOC':
            all_anchor_size = ANCHOR_SIZE

    return all_anchor_size
    
def compute_iou(anchor_boxes, gt_box):
    """
    Input:
        anchor_boxes : ndarray -> [[c_x_s, c_y_s, anchor_w, anchor_h], ..., [c_x_s, c_y_s, anchor_w, anchor_h]].
        gt_box : ndarray -> [c_x_s, c_y_s, anchor_w, anchor_h].
    Output:
        iou : ndarray -> [iou_1, iou_2, ..., iou_m], and m is equal to the number of anchor boxes.
    """
    # compute the iou between anchor box and gt box
    # First, change [c_x_s, c_y_s, anchor_w, anchor_h] ->  [xmin, ymin, xmax, ymax]
    # anchor box :
    ab_x1y1_x2y2 = np.zeros([len(anchor_boxes), 4])
    ab_x1y1_x2y2[:, 0] = anchor_boxes[:, 0] - anchor_boxes[:, 2] / 2  # xmin
    ab_x1y1_x2y2[:, 1] = anchor_boxes[:, 1] - anchor_boxes[:, 3] / 2  # ymin
    ab_x1y1_x2y2[:, 2] = anchor_boxes[:, 0] + anchor_boxes[:, 2] / 2  # xmax
    ab_x1y1_x2y2[:, 3] = anchor_boxes[:, 1] + anchor_boxes[:, 3] / 2  # ymax
    w_ab, h_ab = anchor_boxes[:, 2], anchor_boxes[:, 3]
    
    # gt_box : 
    # We need to expand gt_box(ndarray) to the shape of anchor_boxes(ndarray), in order to compute IoU easily. 
    gt_box_expand = np.repeat(gt_box, len(anchor_boxes), axis=0)

    gb_x1y1_x2y2 = np.zeros([len(anchor_boxes), 4])
    gb_x1y1_x2y2[:, 0] = gt_box_expand[:, 0] - gt_box_expand[:, 2] / 2 # xmin
    gb_x1y1_x2y2[:, 1] = gt_box_expand[:, 1] - gt_box_expand[:, 3] / 2 # ymin
    gb_x1y1_x2y2[:, 2] = gt_box_expand[:, 0] + gt_box_expand[:, 2] / 2 # xmax
    gb_x1y1_x2y2[:, 3] = gt_box_expand[:, 1] + gt_box_expand[:, 3] / 2 # ymin
    w_gt, h_gt = gt_box_expand[:, 2], gt_box_expand[:, 3]

    # Then we compute IoU between anchor_box and gt_box
    S_gt = w_gt * h_gt
    S_ab = w_ab * h_ab
    I_w = np.minimum(gb_x1y1_x2y2[:, 2], ab_x1y1_x2y2[:, 2]) - np.maximum(gb_x1y1_x2y2[:, 0], ab_x1y1_x2y2[:, 0])
    I_h = np.minimum(gb_x1y1_x2y2[:, 3], ab_x1y1_x2y2[:, 3]) - np.maximum(gb_x1y1_x2y2[:, 1], ab_x1y1_x2y2[:, 1])
    S_I = I_h * I_w
    U = S_gt + S_ab - S_I + 1e-20
    IoU = S_I / U
    
    return IoU

def set_anchors(anchor_size, stride, gride_index):
    """
    Input:
        anchor_size : list -> [[h_1, w_1], [h_2, w_2], ..., [h_n, w_n]].
        stride : int -> the downSample of the CNN, such as 32, 64 and so on.
        gride_index: list -> [grid_y, grid_x] is the location in the gride (feature map).
    Output:
        anchor_boxes : ndarray -> [[0, 0, anchor_w, anchor_h],
                                   [0, 0, anchor_w, anchor_h],
                                   ...
                                   [0, 0, anchor_w, anchor_h]].
    """
    grid_y, grid_x = gride_index
    anchor_number = len(anchor_size)
    anchor_boxes = np.zeros([anchor_number, 4])
    for index, size in enumerate(anchor_size): 
        anchor_w, anchor_h = size
        anchor_boxes[index] = np.array([0, 0, anchor_w, anchor_h])
    
    return anchor_boxes

def generate_txtytwth(gt_label, w, h, s, all_anchor_size):
    xmin, ymin, xmax, ymax = gt_label[:-1]
    # map it to the image
    xmin *= w
    ymin *= h
    xmax *= w
    ymax *= h
    # compute the center, width and height
    c_x = (xmax + xmin) / 2
    c_y = (ymax + ymin) / 2
    box_w = xmax - xmin
    box_h = ymax - ymin
    # map the center, width and height to the feature map size
    c_x_s = c_x / s
    c_y_s = c_y / s
    box_ws = box_w / s
    box_hs = box_h / s
    # the gride cell location
    grid_x = int(c_x_s)
    grid_y = int(c_y_s)
    # generate anchor boxes
    anchor_boxes = set_anchors(all_anchor_size, s, [grid_y, grid_x])
    gt_box = np.array([[0, 0, box_ws, box_hs]])
    # compute the IoU
    iou = compute_iou(anchor_boxes, gt_box)
    # We only consider those anchor boxes whose IoU is more than ignore thresh,
    iou_mask = (iou > ignore_thresh).astype(np.int) # bool -> int

    result = []
    if iou_mask.sum() == 0:
        # We assign the anchor box with highest IoU score.
        index = np.argmax(iou)
        p_w, p_h = all_anchor_size[index]
        tx = c_x_s - grid_x
        ty = c_y_s - grid_y
        tw = np.log(box_ws / p_w)
        th = np.log(box_hs / p_h)
        weight = 2.0 - (box_w / w) * (box_h / h)
        
        result.append([index, grid_x, grid_y, tx, ty, tw, th, weight])
        
        return result
    else:
        # We assign any anchor box whose IoU score is higher than ignore thresh.
        iou_ = iou * iou_mask
        for index, iou_score in enumerate(iou_):
            if iou_score > ignore_thresh:
                p_w, p_h = all_anchor_size[index]
                tx = c_x_s - grid_x
                ty = c_y_s - grid_y
                tw = np.log(box_ws / p_w)
                th = np.log(box_hs / p_h)
                weight = 2.0 - (box_w / w) * (box_h / h)
                result.append([index, grid_x, grid_y, tx, ty, tw, th, weight])

        return result 

def generate_dxdywh(gt_label, w, h, s):
    xmin, ymin, xmax, ymax = gt_label[:-1]
    xmin *= w
    ymin *= h
    xmax *= w
    ymax *= h
    # compute box center point coordinate
    c_x = (xmax + xmin) / 2
    c_y = (ymax + ymin) / 2
    # map center point of box to the grid cell
    c_x_s = c_x / s
    c_y_s = c_y / s
    # compute the (x, y, w, h) for the corresponding grid cell
    x = c_x_s - int(c_x_s)
    y = c_y_s - int(c_y_s)
    box_w = (xmax - xmin) / w
    box_h = (ymax - ymin) / h

    return c_x_s, c_y_s, x, y, box_w, box_h

def gt_creator(input_size, stride, num_classes, label_lists=[], use_anchor=False, name='VOC'):
    """
    Input:
        input_size : list -> the size of image in the training stage.
        stride : int or list -> the downSample of the CNN, such as 32, 64 and so on.
        num_classes : int -> the number of class labels.
        label_list : list -> [[[xmin, ymin, xmax, ymax, cls_ind], ... ], [[xmin, ymin, xmax, ymax, cls_ind], ... ]],  
                        and len(label_list) = batch_size;
                            len(label_list[i]) = the number of class instance in a image;
                            (xmin, ymin, xmax, ymax) : the coords of a bbox whose valus is between 0 and 1;
                            cls_ind : the corresponding class label.
        use_anchor : bool -> whether to use anchor boxes.
    Output:
        gt_tensor : ndarray -> shape = [batch_size, anchor_number, 1+1+4, grid_cell number ]
    """
    assert len(input_size) > 0 and len(label_lists) > 0
    # prepare the all empty gt datas
    batch_size = len(label_lists)
    w = input_size[1]
    h = input_size[0]
    
    # We  make gt labels by anchor-free method and anchor-based method.
    ws = w // stride
    hs = h // stride
    s = stride
    # We only make gt labels by anchor-free method or anchor-based method.
    if use_anchor:
        # We use anchor boxes to build training target.
        all_anchor_size = get_total_anchor_size(input_size, stride, name=name)
        anchor_number = len(all_anchor_size)

        gt_tensor = np.zeros([batch_size, hs, ws, anchor_number, 1+1+4+1])
        for batch_index in range(batch_size):
            for gt_label in label_lists[batch_index]:
                # get a bbox coords
                gt_class = int(gt_label[-1])
                results = generate_txtytwth(gt_label, w, h, s, all_anchor_size)
                for result in results:
                    index, grid_x, grid_y, tx, ty, tw, th, weight = result
                    gt_tensor[batch_index, grid_y, grid_x, index, 0] = 1.0
                    gt_tensor[batch_index, grid_y, grid_x, index, 1] = gt_class
                    gt_tensor[batch_index, grid_y, grid_x, index, 2:6] = np.array([tx, ty, tw, th])
                    gt_tensor[batch_index, grid_y, grid_x, index, 6] = weight
    
        gt_tensor = gt_tensor.reshape(batch_size, hs * ws * anchor_number, 1+1+4+1)

        return gt_tensor
    # We don't use anchor boxes, and our training target is anchor-free.  
    else:
        gt_tensor = np.zeros([batch_size, hs, ws, 1+1+4])
        # generate gt whose style is yolo-v1
        for batch_index in range(batch_size):
            for gt_label in label_lists[batch_index]:
                gt_class = int(gt_label[-1])
                c_x_s, c_y_s, x, y, box_w, box_h = generate_dxdywh(gt_label, w, h, s)
                if int(c_x_s) < gt_tensor.shape[2] and int(c_y_s) < gt_tensor.shape[1]:
                    gt_tensor[batch_index, int(c_y_s), int(c_x_s), 0] = 1.0
                    gt_tensor[batch_index, int(c_y_s), int(c_x_s), 1] = gt_class
                    gt_tensor[batch_index, int(c_y_s), int(c_x_s), 2:] = np.array([x, y, box_w, box_h])

        gt_tensor = gt_tensor.reshape(batch_size, -1, 1+1+4)

        return gt_tensor

def multi_gt_creator(input_size, strides, scale_thresholds, num_classes, label_lists=[], use_anchor=False, name='VOC'):
    """creator multi scales gt"""
    if not use_anchor:
        assert len(strides) == len(scale_thresholds)
    # prepare the all empty gt datas
    batch_size = len(label_lists)
    h, w = input_size
    gt_tensor = []

    # generate gt datas
    if use_anchor:
        pass

    else:
        for s in strides:
            gt_tensor.append(np.zeros([batch_size, h//s, w//s, 1+1+4]))

        for batch_index in range(batch_size):
            for gt_label in label_lists[batch_index]:
                gt_class = gt_label[-1]
                # map center point of box to the grid cell
                for index, s in enumerate(strides):
                    thresh = scale_thresholds[index]
                    results = generate_dxdywh(gt_label, w, h, s)
                    c_x_s, c_y_s, x, y, box_w, box_h = results
                    box_area = box_w * box_h
                    area_ratio = box_area # Because the b_w and b_h have been mapped tp the input size scale.

                    if area_ratio > thresh[0] and area_ratio <= thresh[1]:
                        gt_tensor[index][batch_index, int(c_y_s), int(c_x_s), 0] = 1.0
                        gt_tensor[index][batch_index, int(c_y_s), int(c_x_s), 1] = gt_class
                        gt_tensor[index][batch_index, int(c_y_s), int(c_x_s), 2:] = np.array([x, y, box_w, box_h])
                        break
                    else:
                        continue
        # print("s1: ", gt_tensor[0][:,:,:,0].sum())
        # print("s2: ", gt_tensor[1][:,:,:,0].sum())
        # print("s3: ", gt_tensor[2][:,:,:,0].sum())
        # print()
        gt_tensor = [gt.reshape(batch_size, -1, 1+1+4) for gt in gt_tensor]
        gt_tensor = np.concatenate(gt_tensor, 1)
        return gt_tensor

def loss(pred, label, num_classes, use_anchor=False, strides=None, input_size=None, use_focal=False):
    # define loss functions
    if use_focal:
        obj_loss_function = BCE_focal_loss(reduction='mean')
    else:
        obj_loss_function = BCELoss(reduction='mean')
    class_loss_function = nn.CrossEntropyLoss(reduction='none')
    box_loss_function = nn.MSELoss(reduction='none')

    if use_anchor:
        pred_obj = torch.sigmoid(pred[:, :, 0])
        pred_class = pred[:, :, 1 : 1+num_classes].permute(0, 2, 1)
        pred_box = pred[:, :, 1+num_classes:]

        pred_box_xy = torch.sigmoid(pred_box[:, :, :2])
        pred_box_wh = pred_box[:, :, 2:]
        
    else:
        pred_obj = torch.sigmoid(pred[:, :, 0])
        pred_class = pred[:, :, 1:num_classes+1].permute(0, 2, 1)
        pred_box = pred[:, :, num_classes+1:]
        pred_box_xy = torch.sigmoid(pred_box[:, :, :2])
        pred_box_wh = torch.relu(pred_box[:, :, 2:])

    gt_obj = label[:, :, 0].float()
    gt_class = label[:, :, 1].long()
    if use_anchor:
        gt_box = label[:, :, 2:6].float()
        gt_box_scale_weight = label[:, :, -1]
    else:
        gt_box = label[:, :, 2:].float()

    # objectness loss
    if use_focal:
        obj_loss = obj_loss_function(pred_obj, gt_obj)
    else:
        pos_loss, neg_loss = obj_loss_function(pred_obj, gt_obj)
        obj_loss = 1.0  *pos_loss + 0.5 * neg_loss
    
    # class loss
    class_loss = torch.mean(torch.sum(class_loss_function(pred_class, gt_class) * gt_obj, 1))
    
    # box loss
    box_loss_xy = torch.mean(torch.sum(torch.sum(box_loss_function(pred_box_xy, gt_box[:, :, :2]), 2) * gt_obj, 1))
    if use_anchor:
        box_loss_wh = torch.mean(torch.sum(torch.sum(box_loss_function(pred_box_wh, gt_box[:, :, 2:]), 2) * gt_obj, 1))
    else:
        box_loss_wh = torch.mean(torch.sum(torch.sum(box_loss_function(torch.sqrt(pred_box_wh), torch.sqrt(gt_box[:, :, 2:])), 2) * gt_obj, 1))

    box_loss = box_loss_xy + box_loss_wh

    return obj_loss, class_loss, box_loss
        

if __name__ == "__main__":
    gt_box = np.array([[0.0, 0.0, 10, 10]])
    anchor_boxes = np.array([[0.0, 0.0, 10, 10], 
                             [0.0, 0.0, 4, 4], 
                             [0.0, 0.0, 8, 8], 
                             [0.0, 0.0, 16, 16]
                             ])
    iou = compute_iou(anchor_boxes, gt_box)
    print(iou)