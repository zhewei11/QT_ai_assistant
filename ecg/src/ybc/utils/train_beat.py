import numpy as np
import math
from pathlib import Path
from tensorflow import keras
from keras.models import Model
from keras import layers
from keras.layers import Input, Conv1D, MaxPool1D, Activation, Flatten, Dense, Dropout, Softmax, BatchNormalization, GlobalAveragePooling1D, Concatenate
from keras import initializers
from keras.callbacks import EarlyStopping,ModelCheckpoint,ReduceLROnPlateau
SGDM = keras.optimizers.SGD(learning_rate=0.0001,momentum=0.99, nesterov=True, decay=1e-6)
Adam = keras.optimizers.Adam(learning_rate=0.01, beta_1=0.9, beta_2=0.999, epsilon=None, decay=0.8, amsgrad=True)

path = Path(__file__).parent / "../weight"


def train_beat(ecg_train,rr_train,y_train):
    # load weight
    conv1_weight = np.load(f'{path}/Conv1.npy')
    conv1_bias = np.load(f'{path}/Conv1_bias.npy')
    conv2_weight = np.load(f'{path}/Conv2.npy')
    conv2_bias = np.load(f'{path}/Conv2_bias.npy')
    conv3_weight = np.load(f'{path}/Conv3.npy')
    conv3_bias = np.load(f'{path}/Conv3_bias.npy')
    conv4_weight = np.load(f'{path}/Conv4.npy')
    conv4_bias = np.load(f'{path}/Conv4_bias.npy')
    conv5_weight = np.load(f'{path}/Conv5.npy')
    conv5_bias = np.load(f'{path}/Conv5_bias.npy')
    dense1_weight = np.load(f'{path}/Dense1.npy')
    dense1_bias = np.load(f'{path}/Dense1_bias.npy')
    dense2_weight = np.load(f'{path}/Dense2.npy')
    dense2_bias = np.load(f'{path}/Dense2_bias.npy')
    dense3_weight = np.load(f'{path}/Dense3.npy')
    dense3_bias = np.load(f'{path}/Dense3_bias.npy')

    # Training
    # keras toolkit

    input_ECG = Input(shape=(256,1))
    input_RR = Input(shape=(5,1))
    h = Conv1D(filters=16, kernel_size=3, strides=2, padding='same',name="conv1",kernel_initializer=initializers.Constant(conv1_weight),bias_initializer=initializers.Constant(conv1_bias))(input_ECG)
    h = layers.Activation('relu')(h)
    h = Conv1D(filters=16, kernel_size=3, strides=2, padding='same' ,name="conv2",kernel_initializer=initializers.Constant(conv2_weight),bias_initializer=initializers.Constant(conv2_bias))(h)
    h = layers.Activation('relu')(h)
    h = Conv1D(filters=8, kernel_size=3, strides=1, padding='same',name="conv3",kernel_initializer=initializers.Constant(conv3_weight),bias_initializer=initializers.Constant(conv3_bias))(h)
    h = layers.Activation('relu')(h)
    h = Conv1D(filters=1, kernel_size=3, strides=1, padding='same',name="conv4", kernel_initializer=initializers.Constant(conv4_weight),bias_initializer=initializers.Constant(conv4_bias))(h)
    h = layers.Activation('relu')(h)
    h = Flatten()(h)
    r = Conv1D(filters=8, kernel_size=5, strides=1,name="conv5",kernel_initializer=initializers.Constant(conv5_weight),bias_initializer=initializers.Constant(conv5_bias))(input_RR)
    r = layers.Activation('relu')(r)
    r = Flatten()(r)
    concat = Concatenate()([h,r])
    concat = Dense(10,kernel_initializer=initializers.Constant(dense1_weight), bias_initializer=initializers.Constant(dense1_bias))(concat)
    concat = Dense(5,kernel_initializer=initializers.Constant(dense2_weight), bias_initializer=initializers.Constant(dense2_bias))(concat)
    model_output = Dense(5,kernel_initializer=initializers.Constant(dense3_weight), bias_initializer=initializers.Constant(dense3_bias))(concat)
    model = Model(inputs=[input_ECG, input_RR], outputs=model_output,name='model')

    # Freeze specific layer untrainable
    for layer in model.layers[:-2]:
        layer.trainable = False
    # model.summary() 
    model.compile(loss=keras.losses.CategoricalCrossentropy(from_logits=True), optimizer=SGDM, metrics=['accuracy'])

    my_callbacks = [
        EarlyStopping(monitor='val_loss', patience=3, verbose=1, mode='auto'),
        ReduceLROnPlateau(monitor='val_loss', factor=0.9, patience=2, min_lr=1e-20),
        # ModelCheckpoint(filepath=weightfilepath,monitor='val_accuracy',save_best_only=True,save_weights_only=True,save_freq='epoch')
    ]

    rr5_train = rr_train[:,2:7]
    print(rr5_train.shape)
    history = model.fit([ecg_train,rr5_train],y_train, batch_size=32, epochs=100, verbose=2,validation_split=0.2, callbacks = my_callbacks)
    return model
