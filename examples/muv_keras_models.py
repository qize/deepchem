"""
Script that trains multitask tensorflow models on MUV dataset.
"""
from __future__ import print_function
from __future__ import division
from __future__ import unicode_literals

import os
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from deepchem.models.test import TestAPI
from deepchem.utils.save import load_from_disk
from deepchem.datasets import Dataset
from deepchem.featurizers.featurize import DataFeaturizer
from deepchem.featurizers.fingerprints import CircularFingerprint
from deepchem.splits import ScaffoldSplitter
from deepchem.splits import RandomSplitter
from deepchem.datasets import Dataset
from deepchem.transformers import BalancingTransformer
from deepchem.hyperparameters import HyperparamOpt
from deepchem.models.multitask import SingletaskToMultitask
from deepchem import metrics
from deepchem.metrics import Metric
from deepchem.metrics import to_one_hot
from deepchem.models.sklearn_models import SklearnModel
from deepchem.utils.evaluate import relative_difference
from deepchem.models.keras_models.fcnet import MultiTaskDNN


np.random.seed(123)

# Set some global variables up top
reload = True
verbosity = "high"
model = "logistic"

# Create some directories for analysis
# The base_dir holds the results of all analysis
#base_dir = "/scratch/users/rbharath/muv_multitask_analysis"
base_dir = "/scratch/users/rbharath/small_muv_multitask_analysis"
current_dir = os.path.dirname(os.path.realpath(__file__))
#Make directories to store the raw and featurized datasets.
feature_dir = os.path.join(base_dir, "features")
samples_dir = os.path.join(base_dir, "samples")
full_dir = os.path.join(base_dir, "full_dataset")
train_dir = os.path.join(base_dir, "train_dataset")
valid_dir = os.path.join(base_dir, "valid_dataset")
test_dir = os.path.join(base_dir, "test_dataset")
model_dir = os.path.join(base_dir, "model")

# Load MUV dataset
print("About to load MUV dataset.")
dataset_file = os.path.join(
    current_dir, "../datasets/muv.csv.gz")
dataset = load_from_disk(dataset_file)
print("Columns of dataset: %s" % str(dataset.columns.values))
print("Number of examples in dataset: %s" % str(dataset.shape[0]))

# Featurize MUV dataset
print("About to featurize MUV dataset.")
featurizers = [CircularFingerprint(size=1024)]
MUV_tasks = sorted(['MUV-692', 'MUV-689', 'MUV-846', 'MUV-859', 'MUV-644',
                    'MUV-548', 'MUV-852', 'MUV-600', 'MUV-810', 'MUV-712',
                    'MUV-737', 'MUV-858', 'MUV-713', 'MUV-733', 'MUV-652',
                    'MUV-466', 'MUV-832'])
# For debugging purposes
MUV_tasks = MUV_tasks[0:1]
print("Using following tasks")
print(MUV_tasks)
featurizer = DataFeaturizer(tasks=MUV_tasks,
                            smiles_field="smiles",
                            compound_featurizers=featurizers,
                            verbosity=verbosity)
featurized_samples = featurizer.featurize(
    dataset_file, feature_dir,
    samples_dir, shard_size=8192,
    reload=reload)

assert len(featurized_samples) == len(dataset)
# Train/Valid/Test Split dataset
print("About to perform train/valid/test split.")
splitter = RandomSplitter(verbosity=verbosity)
frac_train, frac_valid, frac_test = .8, .1, .1
train_samples, valid_samples, test_samples = \
    splitter.train_valid_test_split(
        featurized_samples, train_dir, valid_dir, test_dir,
        log_every_n=1000, reload=reload)

len_train_samples, len_valid_samples, len_test_samples = \
  len(train_samples), len(valid_samples), len(test_samples)
assert relative_difference(
    len(train_samples), frac_train * len(featurized_samples)) < 1e-3
assert relative_difference(
    len(valid_samples), frac_valid * len(featurized_samples)) < 1e-3
assert relative_difference(
    len(test_samples), frac_test * len(featurized_samples)) < 1e-3

# Generate datasets
print("About to create datasets")
print("MUV_tasks")
print(MUV_tasks)
full_dataset = Dataset(data_dir=full_dir, samples=featurized_samples, 
                        featurizers=featurizers, tasks=MUV_tasks,
                        verbosity=verbosity, reload=reload)
print("full_dataset.get_task_names()")
print(full_dataset.get_task_names())
y = full_dataset.get_labels()
train_dataset = Dataset(data_dir=train_dir, samples=train_samples, 
                        featurizers=featurizers, tasks=MUV_tasks,
                        verbosity=verbosity, reload=reload)
y_train  = train_dataset.get_labels()
valid_dataset = Dataset(data_dir=valid_dir, samples=valid_samples, 
                        featurizers=featurizers, tasks=MUV_tasks,
                        verbosity=verbosity, reload=reload)
y_valid = valid_dataset.get_labels()
test_dataset = Dataset(data_dir=test_dir, samples=test_samples, 
                       featurizers=featurizers, tasks=MUV_tasks,
                       verbosity=verbosity, reload=reload)
y_test = test_dataset.get_labels()
len_train_dataset, len_valid_dataset, len_test_dataset = \
  len(train_dataset), len(valid_dataset), len(test_dataset)

print("len(train_samples), len(train_dataset)")
print(len(train_samples), len(train_dataset))
assert relative_difference(
    len(train_samples), len(train_dataset)) < 1e-3
print("len(valid_samples), len(valid_dataset)")
print(len(valid_samples), len(valid_dataset))
assert relative_difference(
    len(valid_samples), len(valid_dataset)) < 1e-2
print("len(test_samples), len(test_dataset)")
print(len(test_samples), len(test_dataset))
assert relative_difference(
    len(test_samples), len(test_dataset)) < 1e-2

# Transform data
print("About to transform data")
input_transformers = []
output_transformers = []
weight_transformers = [BalancingTransformer(transform_w=True, dataset=train_dataset)]
transformers = input_transformers + output_transformers + weight_transformers
for transformer in transformers:
    transformer.transform(train_dataset)
for transformer in transformers:
    transformer.transform(valid_dataset)
for transformer in transformers:
    transformer.transform(test_dataset)

# Fit tensorflow models
MUV_task_types = {task: "classification" for task in MUV_tasks}
classification_metric = Metric(metrics.roc_auc_score, np.mean,
                               verbosity=verbosity,
                               mode="classification")

params_dict = {
    "nb_hidden": [1000],
    "activation": ["relu"],
    "dropout": [.25],
    "learning_rate": [.001],
    "momentum": [.9],
    "nesterov": [False],
    "decay": [1e-4],
    "batch_size": [64],
    "nb_epoch": [10],
    "init": ["glorot_uniform"],
    "nb_layers": [1],
    "batchnorm": [False],
    "data_shape": [train_dataset.get_data_shape()]
}

def keras_multitask_model_builder(tasks, task_types, params_dict, model_dir, logdir=None,
                                  verbosity=None):
  return MultiTaskDNN(tasks, task_types, params_dict, model_dir,
                      verbosity=verbosity)
optimizer = HyperparamOpt(keras_multitask_model_builder, MUV_tasks, MUV_task_types,
                          verbosity=verbosity)

best_dnn, best_dnn_hyperparams, all_dnn_results = \
    optimizer.hyperparam_search(
        params_dict, train_dataset, valid_dataset, output_transformers,
        classification_metric, logdir=model_dir, use_max=True)
