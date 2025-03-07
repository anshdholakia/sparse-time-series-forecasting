from importlib import reload
from math import pi as PI
import os
from os import system
from random import random, seed, sample
from sys import platform, modules
from tempfile import TemporaryDirectory

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import KFold
import tensorflow as tf
from tensorflow.keras import Sequential
from tensorflow.keras.layers import LSTM, Dropout, Activation, Dense, Embedding
from tensorflow.keras.callbacks import EarlyStopping
from tensorflow.keras.optimizers import Adam
from wfdb.io import rdrecord
from sklearn.model_selection import KFold

from model import Activity, Dictionary, SparseModel, sparsity_loss, dictionary_loss

def loadDataSample(nsamples=100, npoints=100000, nperiods=100, random_state=42, variation_parm=1):
	"""
	DESCRIPTION
	-----------
	

	PARAMETERS
	----------
	nsamples: 

	npoints: 

	nperiods: 

	seed: 

	variation_parm:


	RETURNS
	-------
	x: 

	"""

	seed(random_state)

	t = np.linspace(0, nperiods * PI, npoints)
	x = np.array([np.sin(t) + variation_parm * 0.01 * (random() - 0.5) for _ in range(nsamples)])
	return x	


def plotOneSample(dataloc):
	pass


def getDataFiles(tempdir):
	filenames = []
	datadir = os.path.join(tempdir, 'physionet.org/files/ptbdb/1.0.0/')
	patientfiles = [e for e in os.listdir(datadir) if 'patient' in e]
	for patientfile in patientfiles:
		patientdir = os.path.join(datadir, patientfile)
		datafiles = [e for e in os.listdir(patientdir)]
		datafiles_base = [e.split('.')[0] for e in datafiles if e != 'index.html']
		for datafile in set(datafiles_base):
			dataloc = os.path.join(patientdir, datafile)
			filenames.append(dataloc)
	return filenames


def loadData(tempdir=None, npatients=500, npoints=100000):
	"""
	DESCRIPTION
	-----------
	This function will download approximately 1.7 G in a temporary directory. I used the following logic when creating this function in order to ensure reproducibility. 

	# 1. create temp directory (tempfile)
	# 2. download data from url to temp file
	# --- command = wget -r -N -c -np https://physionet.org/files/ptbdb/1.0.0/
	# --- use os.system(command)
	# 3. return temp file name
	# 4. open and read the contents of the downloaded file
	# 5. append to numpy array

	Usage:
		data, tempdir = loadData()
		or 
		data, tempdir = loadData(tempdir)

	PARAMETERS
	----------
	tempdir: str (default=None)
		Path to temporary directory storing the data downloaded by this function. If not provided, the data will be redownloaded in a separate temporary directory. If this recently ran and the temporary directory file path is saved, pass it in as this argument. 
	npatients: int (default=100)
		Number of samples to use at most from the downloaded data.
	npoitnts:
		Number of points to use for each sample. Samples with less points than this value will be excluded.
	RETURNS
	-------
	data:	
		Numpy ndarray representing the ECG data.
	tempdir:
		Path to temporary directory where the data is downloaded.
	"""

	# def loadDataHelper(data):
	# 	return data

	data = np.zeros((0, npoints))

	if not tempdir:
		tempdir = TemporaryDirectory().name
		try:
			if platform == "win32":
				system("wsl -r -N -c -np -P %s https://physionet.org/files/ptbdb/1.0.0/" % tempdir)
			if platform == "darwin":
				system("wget -r -N -c -np -P %s https://physionet.org/files/ptbdb/1.0.0/" % tempdir)
			else:
				print("I don't know what platform you have... Tell Ethan on Slack.")
				return None, None
		except Exception as e:
			print("[%s]:[%s] %s" % __name, __func__, e)
			print("Make sure if you are on Windows that you have wsl install. If you are on Mac, please install wget.")
			return None, None

	for dataloc in getDataFiles(tempdir):
		if data.shape[0] == npatients:
			break
		rec = rdrecord(dataloc, channels=[0])
		x = rec.p_signal
		if x is None:
			x = rec.d_signal
		if x is None:
			continue
		if len(x) < npoints:
			continue
		x_t = np.transpose(x)
		data = np.vstack([data, x_t[:, 0:npoints]])

	return data, tempdir


def getSegments(data, npatients=500, nfeature_points=64000, ntarget_points=128, nsamples_per_patient=100, random_state=42):
	"""
	DESCRIPTION
	-----------
	Points selected for ntrain_points and mtest_points need to be adjacent, but they do not necessarily need to be fetched from the beginning of the file.

	PARAMETERS
	----------
	data: (after preprocessed/selected)

	nsamples: number of random samples to choose from data

	ntrain_points: int
		Number of points in training set
	mtest_points: int
		Number of points in the test set

	RETURNS
	-------
	tuple: 
		Tuple of samples separated into ntrain_points and mtest_points

	"""

	seed(random_state)

	npoints = data.shape[1]

	X = np.zeros((0, nfeature_points))
	y = np.zeros((0, ntarget_points))

	for i in range(npatients):
		for _ in range(nsamples_per_patient):
			a = int(random() * (npoints - (nfeature_points + ntarget_points)))
			b = a + nfeature_points
			c = b + ntarget_points

			X = np.vstack([X, data[i][a:b]])
			y = np.vstack([y, data[i][b:c]])

	# x_train = np.array([np.nan_to_num(e, nan=0, posinf=0, neginf=0) for e in x_train])
	# y_train = np.array([np.nan_to_num(e, nan=0, posinf=0, neginf=0) for e in y_train])

	# x_test = np.array([np.nan_to_num(e, nan=0, posinf=0, neginf=0) for e in x_test])
	# y_test = np.array([np.nan_to_num(e, nan=0, posinf=0, neginf=0) for e in y_test])

	return X, y


def getSparseRepresentation(X, batch_size=200, num_filters=100, patches_per_img=50, alpha=0.01, beta=0.99, epsilon=1e-6, sparsity_coef=1, activity_epochs=300, epochs=30, num_layers=1, verbose=False, save=True):
	"""
	DESCRIPTION
	-----------
	# Use Isamu's module to do this...
	# This function accepts the first element of the tuple returned from getSegments
	
	PARAMETERS
	----------
	

	RETURNS
	-------
	
	"""

	data_size = X.shape[0]
	sample_size = X.shape[1]

	dict_filter_size = 32

	X_ = X.reshape([-1, dict_filter_size])

	scaler = StandardScaler()
	scaler.fit(X_)

	X_ = scaler.transform(X_)

	callback = EarlyStopping(monitor='dictionary loss', patience=3)

	sparse_activity_obj = Activity(batch_size=batch_size, units=num_filters, alpha=alpha, sparsity_coef=sparsity_coef)
	sparse_dictionary_obj = Dictionary(units=num_filters, dict_filter_size=dict_filter_size, beta=beta)
	sparse_model = SparseModel(sparse_activity_obj, sparse_dictionary_obj, batch_size=batch_size, activity_epochs=activity_epochs, dict_filter_size=dict_filter_size, data_size=data_size, num_layers=num_layers)
	sparse_model.compile(sparsity_loss, dictionary_loss)

	history = sparse_model.fit(X_, epochs=epochs, batch_size=batch_size, callbacks=[callback])

	if verbose:
		# sparse_model.summary()
		plotSparseReconstruction(sparse_model, num_filters)

	if save:
		try:
			sparse_model.save_weights('sparse_weights.h5')
		except:
			print("Saving?")

	return sparse_model


# TODO: find a better way to visualize the dictionary
# def plotSparseReconstruction(sparse_model, num_filters=100, num_cols=10):
# 	fig = plt.figure(figsize=(20, 20))
# 	gs = fig.add_gridspec(num_filters // num_cols, num_cols, hspace=0, wspace=0)
# 	axs = gs.subplots(sharex='col', sharey='row')
# 	for i in range(num_filters):
# 		axs[i // num_cols][i % num_cols].imshow(tf.reshape(sparse_model.dictionary.w[:, i], shape=[32,1]))
# 	plt.show()


def score(y_pred, sparse_model):
	"""
	DESCRIPTION
	-----------
	1. weight_function would cause the score function called to be time dependent. 

	PARAMETERS
	----------
	

	RETURNS
	-------
	
	"""

	y_pred_reconstruction = sparse_model.call(y_pred)

	nsamples = len(y_pred)

	sparse_activity = sparse_model.activity.w[:nsamples, :]

	np.mean([e for e in sparse_activity])

	# R = sparse_activity @ tf.transpose(sparse_dictionary)

	# sqrt(sum([(x_act[i] - x_pred[i]) ** 2 for i in range(x_pred)]))

	return error 



def buildModel(x_train, output_size, neurons=100, activ_func="relu", dropout=0.5, loss="mse", verbose=False):
	"""
	DESCRIPTION
	-----------
	This will simply return a compiled model

	PARAMETERS
	----------
	inputs: input data as an array

	n_outputs: number of predictions we want per sample

	neurons: number of neurons in the LSTM layer

	activ_func: activation function (e.g. tanh, sigmoid, etc.)

	dropout: value for the Dropout Layer

	optimizer: type of optimizer to use for model (e.g adam, rmsprop, etc.)

	RETURNS
	-------
	A compiled LSTM model and model summary (optional)
	
	"""
	model = Sequential()
	model.add(LSTM(neurons, input_shape=(x_train.shape[1:]), activation=activ_func))
	model.add(Dense(units=output_size))

	model.compile(loss=loss, optimizer=Adam(learning_rate=0.01), metrics=['mae'])

	if verbose:
		model.summary()

	return model



def predictForecast(X_train, y_train, X_test, weights=None, epochs=300, batch_size=10, verbose=False, save=True):
	"""
	DESCRIPTION
	-----------
	

	PARAMETERS
	----------
	

	RETURNS
	-------
	
	"""

	# Randomize those weights some how

	scaler = StandardScaler()
	scaler.fit(X_train)

	X_train_ = scaler.transform(X_train)
	X_test_ = scaler.transform(X_test)

	X_train_ = X_train_.reshape((X_train_.shape[0], 1, X_train_.shape[1]))
	X_test_ = X_test_.reshape((X_test_.shape[0], 1, X_test_.shape[1]))

	model = buildModel(X_train_, y_train.shape[1])

	if weights:
		model.layers[0].set_weights(weights)

	callback = EarlyStopping(monitor='loss', patience=3)

	history = model.fit(X_train_, y_train, epochs=epochs, batch_size=batch_size, callbacks=[callback])

	y_pred = model.predict(X_test_)
	
	weights = model.layers[0].get_weights()

	if save:
		# np.savefile(weights)
		pass

	return y_pred, weights


def runGeneticAlgorithm(X, y, ngenerations=10, nchildren=100, nepochs=200, alpha=0.05):
	"""
	DESCRIPTION
	-----------
	

	PARAMETERS
	----------
	

	RETURNS
	-------
	
	"""

	sparse_model = getSparseRepresentation(X)
	
	weights = None

	ntop_weights = int(nchildren * alpha)

	kf = KFold(ngenerations)

	for train_index, test_index in kf.split(X):

		X_train = X[train_index, ]
		y_train = y[train_index, ]

		X_test = X[test_index, ]
		y_test = X[test_index, ]

		child_weights = []
		child_scores = []

		for _ in range(nchildren):
			# Randomize the weights for each child
			weights_random = None

			y_pred, weights = predictForecast(X_train, y_train, X_test, weights=weights_random)

			child_weights.append(weights_random)

			child_scores.append(score(y_pred, sparse_model))

		best_weights = child_weights[np.argsort(np.array([np.mean(child_score) for child_score in child_scores]))[0:ntop_weights]]

		# Use top weights to create new weights

		# After each epoch create weights
		weights = None

		return weights


def main():
	"""
	DESCRIPTION
	-----------
	

	PARAMETERS
	----------
	

	RETURNS
	-------
	
	"""

	tempdir = '/Users/ethanmoyer/Projects/drexelai/data/sparse-time-series-forecasting'

	data, tempfir = loadData(tempdir=tempdir, npatients=50)
	X, y = getSegments(data, npatients=50, nsamples_per_patient=1)
	results = runGeneticAlgorithm(X, y, nchildren=100, nepochs=20, alpha=0.05)


if __name__ == "__main__":
	pass
	#main()



