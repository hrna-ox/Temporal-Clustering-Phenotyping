#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Loss, Metrics and Callback functions to use for model

@author: henrique.aguiar@ds.ccrg.kadooriecentre.org
"""
import tensorflow as tf
import tensorflow.math as math
from tensorflow.math import log, squared_difference, multiply, divide

from datetime import date
import numpy as np

import os

# Loss functions
def propagate_true_event_across_time(y, num_tstpms):
    
    """
    Function to propagate true event across each time subsequence if not already done so.
    """
    if len(y.get_shape()) == 2:
        # if time dimension missing, outcome is propagated to all the sub-sequences
        y = tf.repeat(tf.expand_dims(y, axis = 1),
                           repeats = num_tstpms, axis = 1, name = 'propagate_outc')
        
    elif len(y.get_shape()) == 3:
        y = y
    
    else:
        print(y.get_shape())
        print("Error - y true does not have the right shape.")
        return None
    
    return y

val_data_weights = np.array([7992, 954, 162, 108])
uniform          = np.array([1, 1, 1, 1])
harmonic_weights = 1 / val_data_weights
weights = tf.convert_to_tensor(harmonic_weights / np.sum(harmonic_weights), dtype = tf.float32)

# Define custom loss functions
def predictive_clustering_loss(y_true, y_pred, weights = weights,  y_type = 'categorical', name = 'pred_clus_L'):
    
    """
    Compute prediction clustering loss between predicted output and true output.
    
    y_pred shape : (batch_size, T, num_classes) 
    y_true shape : (batch_size, num_classes)  or (batch_size, T, num_classes). If the former, add dimension and repeat.
    
    y_type:
        - Binary:  Computes Binary Cross Entropy. Class/Event occurence is matched with a dimension.
                    y_true with entries in [0,1], and y_pred with value between (0,1)
                    
        - Categorical: Computes Cross Entropy Loss. Class assigned by highest value dimension.
                    y_true is a one-hot encoding, and y_pred is a probabilistic vector.
                    
        - Continuous: Computes L2 loss. Similar to the Binary case, but class attributes are continuous.
                    y_true and y_pred both with real-value entries.

    Returns: Loss value between sample true y and predicted y based on y_type
    """
    # weights = tf.convert_to_tensor(np.array([4266/3701, 4266/441, 4266/76, 4266/48], dtype = "float32"))
    
    # Compute Loss Functions according to y_type
    if y_type == 'binary':
        # Compute Binary Cross Entropy. y_pred output of sigmoid function to avoid taking log of infty.
        batch_loss = - tf.reduce_mean(tf.reduce_sum(y_true * log(y_pred) + (1 - y_true) * log(y_pred),
                                                    axis = -1), name = name)

    elif y_type == 'categorical':
        # Compute Categorical Cross Entropy. y_pred output of softmax function to model probability vector.
        # weigh_cat_loss = y_true * log(y_pred) * tf.expand_dims(tf.expand_dims(weights, axis = 0), axis = 0)
        
        # batch_loss = -tf.reduce_mean(tf.reduce_sum(weigh_cat_loss, axis = -1), name = name)
        batch_loss = -tf.reduce_mean(tf.reduce_sum(weights * y_true * log(y_pred), axis = -1), name = name)

    elif y_type == 'continuous':
        # Compute L2 Loss. y_pred not given final output function.
        batch_loss = tf.reduce_mean(tf.reduce_sum((y_true - y_pred) ** 2, axis = -1), name = name)

    else:
        raise Exception("""y_type not well-defined. Only possible values are {'binary', 'categorical',
                                                                                       'continuous'}""")
    return batch_loss


def selector_init_loss(clusters, y_prob, name = 'init_selec_loss'):
    """
    Selector Loss for Initialisation. Initialise Selector given estimated cluster assignments.
    
    Input shape: (batch_size, T, num_clusters) is a probabilistic vector.
    
    returns: Categorical Cross-Entropy loss averaged over samples and time-steps. This is very similar to predictive
    clustering loss with cluster assignment constant across time
    """
    # Compute Categorical Cross Entropy. y_pred output of softmax function to model probability vector.
    batch_loss = -tf.reduce_mean(tf.reduce_sum(clusters * log(y_prob), axis = -1), name = name)

    return batch_loss


def actor_predictive_clustering_loss(y_true, y_pred, cluster_assignment_probs, y_type = 'categorical',
                                     name = 'actor_pred_clus_L'):
    """
    Compute prediction clustering loss between predicted output and true output with probability weights
    from cluster assignments.
    
    y_true shape : (batch_size, T, num_classes)
    y_pred shape : (batch_size, T, num_classes) or (batch_size, num_classes)
    cluster_probs shape : (batch_size, T)

    y_type:
        - Binary:  Computes Binary Cross Entropy. Class/Event occurence is matched with a dimension.
                    y_true with entries in [0,1], and y_pred with value between (0,1)
        - Categorical: Computes Cross Entropy Loss. Class assigned by highest value dimension.
                    y_true is a one-hot encoding, and y_pred is a probabilistic vector.
        - Continuous: Computes L2 loss. Similar to the Binary case, but class attributes are continuous.
                    y_true and y_pred both with real-value entries.

    Returns: Loss value between sample true y and predicted y based on y_type of shape (batch_size)
    """
    # Compute Loss functions depending on y_type
    if y_type == 'binary':
        
        # Compute Binary Cross Entropy weighted by cluster assignment probabilities.
        sample_loss = multiply(tf.reduce_sum(y_true * log(y_pred) + (1 - y_true) * log(y_pred), axis = -1),
                               cluster_assignment_probs)
        batch_loss = -tf.reduce_mean(sample_loss, name = name)

        return batch_loss

    elif y_type == 'categorical':
        
        # Compute Categorical Cross Entropy weighted by cluster assignment probabilities.
        sample_loss = multiply(tf.reduce_sum(y_true * log(y_pred), axis = -1), cluster_assignment_probs)
        batch_loss = -tf.reduce_mean(sample_loss, name = name)

        return batch_loss

    elif y_type == 'continuous':
        
        # Compute L2 Loss weighted by cluster assigment probabilities.
        sample_loss = multiply(tf.reduce_sum((y_true - y_pred) ** 2, axis = -1), cluster_assignment_probs)
        batch_loss = tf.reduce_mean(sample_loss, name = name)

        return batch_loss


def cluster_probability_entropy_loss(y_prob, name = 'clus_entr_L'):
    
    """
    Compute Entropy loss on Cluster Probability assignments.
    
    y_prob shape: (batch_size, num_classes), and is a probabilistic vector.

    Returns: Entropy loss, defined as - sum pi*log(pi) with minimum obtained by one-hot probability vectors.
    """
    batch_loss = -tf.reduce_mean(tf.reduce_sum(y_prob * log(y_prob), axis = -1), name = name)

    return batch_loss


def euclidean_separation_loss(y_clusters, name = 'emb_sep_L'):
    """
    Compute Embedding separation Loss on embedding vectors.

    y_clusters: shape (num_clusters, output_dim) - for each cluster i, y_embeddings[i] is the
    corresponding phenotype of the cluster embedding in latent dimension.

    return: A Embedding separation loss (how separate are the clusters in the latent space). Only L1
    loss in latent space considered so far.
    """
    embedding_column = tf.expand_dims(y_clusters, axis = 1)  # shape K, 1, latent_dim
    embedding_row = tf.expand_dims(y_clusters, axis = 0)  # shape 1, K, latent_dim

    # Compute L1 distance
    pairwise_loss = tf.reduce_sum((embedding_column-embedding_row)**2, axis = -1)  # shape K, K
    loss = - tf.reduce_sum(pairwise_loss, axis = None, name = name)
     
    # normalise
    norm_factor = tf.math.subtract(tf.math.square(y_clusters.get_shape()[1]), y_clusters.get_shape()[1])
    norm_loss = tf.math.divide(loss, tf.cast(norm_factor, dtype = "float32"))

    return norm_loss


def KL_separation_loss(y_clusters, name = "KL_emb_sep"):
    """
    Compute symmetric KL divergence between clusters phenotypes.

    Parameters
    ----------
    y_clusters : shape (1, num_clusters, output_dim) - for each cluster i, y_clusters8i9 is the 
    corresponding phenotype of the cluster embedding in loutput dimension.
    
    Returns
    -------
    Symmetric KL separation loss between cluster phenotypes
    """
    embedding_column = tf.expand_dims(y_clusters, axis = 2)     # shape 1, K, 1, latent_dim
    embedding_row    = tf.expand_dims(y_clusters, axis = 1)     # shape 1, 1, K, latent_dim
    
    # Compute logs and KL divergence
    logs = log(math.divide_no_nan(embedding_column, embedding_row))     # shape 1, K, K, latent_dim
    KL_div = multiply(embedding_column, logs)                           # shape 1, K, K, latent_dim
    
    # Num clusters
    num_clusters = y_clusters.get_shape()[1]
    norm_factor = multiply(num_clusters, num_clusters - 1)
    
    # Sum over pairs of clusters
    loss = - divide(tf.math.reduce_sum(KL_div, axis = None), tf.cast(norm_factor, dtype = "float32"))

    return loss




#Define custom metric





