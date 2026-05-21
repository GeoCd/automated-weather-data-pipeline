import numpy as np
import pandas as pd
import pickle

from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error

from tf_keras.models import Sequential, load_model
from tf_keras.layers import LSTM, Dense, Dropout
from tf_keras.callbacks import EarlyStopping

import src.workflows.weather_workflow as workflow
from src.config import WorkflowConfiguration
config = WorkflowConfiguration()

def model_train(df: pd.DataFrame, station: str):
    config.MODEL_DIR.mkdir(exist_ok=True)

    series = df["Temperature(F)"].dropna().values.reshape(-1, 1)

    lstmScaler = MinMaxScaler()
    scaled = lstmScaler.fit_transform(series)

    X, y = [], []
    for i in range(config.LOOK_BACK, len(scaled)):
        X.append(scaled[i - config.LOOK_BACK:i, 0])
        y.append(scaled[i, 0])

    X = np.array(X)
    y = np.array(y)

    splitIdx = int(len(X) * 0.8)
    X_train, X_test = X[:splitIdx], X[splitIdx:]
    y_train, y_test = y[:splitIdx], y[splitIdx:]

    X_train = X_train.reshape(-1, config.LOOK_BACK, 1)
    X_test  = X_test.reshape(-1,  config.LOOK_BACK, 1)

    lstmModel = Sequential([
                            LSTM(64, return_sequences=True, input_shape=(config.LOOK_BACK, 1)),
                            Dropout(0.2),
                            LSTM(32),
                            Dropout(0.2),
                            Dense(1)
                            ])

    lstmModel.compile(optimizer="adam", loss="mse")

    earlyStopping = EarlyStopping(monitor="val_loss", patience=config.PATIENCE, restore_best_weights=True)

    lstmModel.fit(X_train, y_train,
                  epochs=config.EPOCHS,
                  batch_size=config.BATCH_SIZE,
                  validation_split=0.1,
                  callbacks=[earlyStopping],
                  verbose=1
                  )

    modelpath = config.MODEL_DIR / f"lstm_{station}.h5"
    lstmModel.save(modelpath, save_format="h5")
    scalerpath = config.MODEL_DIR / f"lstm_{station}_scaler.pkl"
    with open(scalerpath, "wb") as f:
        pickle.dump(lstmScaler, f)

    print(f"Model saved to: {lstmModel}")

    predScaled = lstmModel.predict(X_test)
    pred = lstmScaler.inverse_transform(predScaled)
    real = lstmScaler.inverse_transform(y_test.reshape(-1, 1))

    metrics =   {
                "rmse": float(np.sqrt(mean_squared_error(real, pred))),
                "mae":  float(mean_absolute_error(real, pred))
                }

    print(f"RMSE: {metrics['rmse']}°F")
    print(f"MAE: {metrics['mae']}°F")

    return metrics

def model_predict(df: pd.DataFrame, station: str):
    """Loads the trained model & generates predictions"""
    modelpath = config.MODEL_DIR / f"lstm_{station}.h5"
    scalerpath = config.MODEL_DIR / f"lstm_{station}_scaler.pkl"
    lstmModel  = load_model(modelpath)
    with open(scalerpath, "rb") as f:
        lstmScaler = pickle.load(f)

    series = df["Temperature(F)"].dropna().values.reshape(-1, 1)
    scaled = lstmScaler.transform(series)

    X = []
    for i in range(config.LOOK_BACK, len(scaled)):
        X.append(scaled[i - config.LOOK_BACK:i, 0])

    X = np.array(X)
    X = X.reshape(-1, config.LOOK_BACK, 1)

    predScaled = lstmModel.predict(X, verbose=0)
    pred = lstmScaler.inverse_transform(predScaled).flatten()

    predIndex = df["Temperature(F)"].dropna().index[config.LOOK_BACK:]

    predDf =    pd.DataFrame({
                            "DateTime": predIndex,
                            "Temperature_Real": df["Temperature(F)"].dropna().values[config.LOOK_BACK:],
                            "Temperature_Pred": pred,
                            "Error": df["Temperature(F)"].dropna().values[config.LOOK_BACK:] - pred
                            }).set_index("DateTime")

    return predDf

def run_model(df: pd.DataFrame,station: str, trainAgain: bool = False):
    metrics = {}

    modelpath = config.MODEL_DIR / f"lstm_{station}.h5"
    if trainAgain or not modelpath.exists():
        print("Training model:")
        metrics = model_train(df, station)
    else:
        print(f"Loading existing model: {modelpath}")

    predDf = model_predict(df,station)
    return predDf, metrics


if __name__ == "__main__":
    df = workflow.run_workflow()
    run_model(df,"MMMX" ,trainAgain=True)
