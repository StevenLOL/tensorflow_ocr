import tensorflow as tf
import numpy as np

from tensorflow.contrib import slim

tf.app.flags.DEFINE_integer('text_scale', 512, '')

from nets import resnet_v1
from nets import resnet_v2

FLAGS = tf.app.flags.FLAGS


def unpool(inputs):
    return tf.image.resize_bilinear(inputs, size=[tf.shape(inputs)[1]*2,  tf.shape(inputs)[2]*2])


def mean_image_subtraction(images, means=[123.68, 116.78, 103.94]):
    '''
    image normalization
    :param images:
    :param means:
    :return:
    '''
    num_channels = images.get_shape().as_list()[-1]
    if len(means) != num_channels:
      raise ValueError('len(means) must match the number of channels')
    channels = tf.split(axis=3, num_or_size_splits=num_channels, value=images)
    for i in range(num_channels):
        channels[i] -= means[i]
    return tf.concat(axis=3, values=channels)

def model_resnet_v1_101(images, weight_decay=1e-5, is_training=True):
    '''
    define the model, we use slim's implemention of resnet
    '''
    images = mean_image_subtraction(images)

    with slim.arg_scope(resnet_v1.resnet_arg_scope(weight_decay=weight_decay)):
        logits, end_points = resnet_v1.resnet_v1_101(images, is_training=is_training, scope='resnet_v1_101')

    with tf.variable_scope('feature_fusion', values=[end_points.values]):
        batch_norm_params = {
        'decay': 0.997,
        'epsilon': 1e-5,
        'scale': True,
        'is_training': is_training
        }
        with slim.arg_scope([slim.conv2d],
                            activation_fn=tf.nn.relu,
                            normalizer_fn=slim.batch_norm,
                            normalizer_params=batch_norm_params,
                            weights_regularizer=slim.l2_regularizer(weight_decay)):
            f = [end_points['pool5'], end_points['pool4'],
                 end_points['pool3'], end_points['pool2']]
            for i in range(4):
                print('Shape of f_{} {}'.format(i, f[i].shape))
            g = [None, None, None, None]
            h = [None, None, None, None]
            num_outputs = [None, 128, 64, 32]
            for i in range(4):
                if i == 0:
                    h[i] = f[i]
                else:
                    c1_1 = slim.conv2d(tf.concat([g[i-1], f[i]], axis=-1), num_outputs[i], 1)
                    h[i] = slim.conv2d(c1_1, num_outputs[i], 3)
                if i <= 2:
                    g[i] = unpool(h[i])
                else:
                    g[i] = slim.conv2d(h[i], num_outputs[i], 3)
                print('Shape of h_{} {}, g_{} {}'.format(i, h[i].shape, i, g[i].shape))

            # here we use a slightly different way for regression part,
            # we first use a sigmoid to limit the regression range, and also
            # this is do with the angle map
            F_score = slim.conv2d(g[3], 1, 1, activation_fn=tf.nn.sigmoid, normalizer_fn=None)
            # 4 channel of axis aligned bbox and 1 channel rotation angle
            geo_map = slim.conv2d(g[3], 4, 1, activation_fn=tf.nn.sigmoid, normalizer_fn=None) * FLAGS.text_scale
            angle_map = (slim.conv2d(g[3], 1, 1, activation_fn=tf.nn.sigmoid, normalizer_fn=None) - 0.5) * np.pi/2 # angle is between [-45, 45]
            F_geometry = tf.concat([geo_map, angle_map], axis=-1)

    return F_score, F_geometry

def model(images, weight_decay=1e-5, is_training=True):
    '''
    define the model, we use slim's implemention of resnet
    '''
    images = mean_image_subtraction(images)

    with slim.arg_scope(resnet_v1.resnet_arg_scope(weight_decay=weight_decay)):
        logits, end_points = resnet_v1.resnet_v1_50(images, is_training=is_training, scope='resnet_v1_50')

    with tf.variable_scope('feature_fusion', values=[end_points.values]):
        batch_norm_params = {
        'decay': 0.997,
        'epsilon': 1e-5,
        'scale': True,
        'is_training': is_training
        }
        with slim.arg_scope([slim.conv2d],
                            activation_fn=tf.nn.relu,
                            normalizer_fn=slim.batch_norm,
                            normalizer_params=batch_norm_params,
                            weights_regularizer=slim.l2_regularizer(weight_decay)):
            feature_maps = [end_points['pool5'], end_points['pool4'],
                 end_points['pool3'], end_points['pool2']]

            for i in range(4):
                print('Shape of f_{} {}'.format(i, feature_maps[i].shape))
            g = [None, None, None, None]
            h = [None, None, None, None]
            num_outputs = [2, 128, 64, 32]
            PIXEL_OUTPUT = 2
            LINK_OUTPUT = 16
            # for i in range(4):
                # if i == 0:
                    # h[i] = feature_maps[i]
                # else:
                    # c1_1 = slim.conv2d(tf.concat([g[i-1], feature_maps[i]], axis=-1), num_outputs[i], 1)
                    # h[i] = slim.conv2d(c1_1, num_outputs[i], 3)
                # if i <= 2:
                    # g[i] = unpool(h[i])
                # else:
                    # g[i] = slim.conv2d(h[i], num_outputs[i], 3)
                # print('Shape of h_{} {}, g_{} {}'.format(i, h[i].shape, i, g[i].shape))
            # for i in range(4):
                # print('Shape of f_{} {}'.format(i, feature_maps[i].shape))
            
            pixel_1 = unpool(slim.conv2d(feature_maps[0], PIXEL_OUTPUT, 1)) + slim.conv2d(feature_maps[1], PIXEL_OUTPUT, 1)
            pixel_2 = unpool(pixel_1) + slim.conv2d(feature_maps[2], PIXEL_OUTPUT, 1)
            pixel_3 = unpool(pixel_2) + slim.conv2d(feature_maps[3], PIXEL_OUTPUT, 1)

            link_1 = unpool(slim.conv2d(feature_maps[0], LINK_OUTPUT, 1)) + slim.conv2d(feature_maps[1], LINK_OUTPUT, 1)
            link_2 = unpool(link_1) + slim.conv2d(feature_maps[2], LINK_OUTPUT, 1)
            link_3 = unpool(link_2) + slim.conv2d(feature_maps[3], LINK_OUTPUT, 1)
            print('Shape of pixel {}, link {}'.format( pixel_3.shape, link_3.shape))

            # this is do with the angle map
            pixel_4 = slim.conv2d(pixel_3, PIXEL_OUTPUT, 1, activation_fn=None, normalizer_fn=None)
            # pixel_4 = slim.conv2d(g[3], 2, 1, activation_fn=tf.nn.sigmoid, normalizer_fn=None)
            link_4 = slim.conv2d(link_3, LINK_OUTPUT, 1, activation_fn=None, normalizer_fn=None)

    return pixel_4, link_4

def dice_coefficient(y_true_cls, y_pred_cls,
                     training_mask):
    '''
    dice loss
    :param y_true_cls:
    :param y_pred_cls:
    :param training_mask:
    :return:
    '''
    eps = 1e-5
    intersection = tf.reduce_sum(y_true_cls * y_pred_cls * training_mask)
    union = tf.reduce_sum(y_true_cls * training_mask) + tf.reduce_sum(y_pred_cls * training_mask) + eps
    loss = 1. - (2 * intersection / union)
    tf.summary.scalar('classification_dice_loss', loss)
    return loss

def loss(y_true_pixel, y_pred_pixel,
         y_true_link, y_pred_link,
         training_mask):
    '''
    return pixel loss and link loss 
    add OHEM mode
    '''
    
    pixel_label = tf.cast(tf.reshape(y_true_pixel,[-1]), tf.int32)
    pixel_pred = tf.reshape(y_pred_pixel, [-1, 2])

    classification_loss = tf.reduce_mean(tf.nn.sparse_softmax_cross_entropy_with_logits(labels = pixel_label, logits = pixel_pred))
    # classification_loss = dice_coefficient(y_true_pixel, y_pred_pixel, training_mask)
    classification_loss *= 2

    link_label = tf.cast(tf.reshape(y_true_link, [-1]), tf.int32)
    link_pred = tf.reshape(y_pred_link, [-1, 2])

    softmax_loss = tf.reduce_mean((tf.nn.sparse_softmax_cross_entropy_with_logits(labels = link_label, logits = link_pred)))

    link_loss = softmax_loss

    tf.summary.scalar('classification_loss', classification_loss)
    tf.summary.scalar('link_loss', link_loss)

    return link_loss + classification_loss
