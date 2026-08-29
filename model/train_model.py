import os
import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

# 1. Load Dataset
df = pd.read_csv("dataset/dataset_ifoox_proposal.csv")

# 2. Encoding variabel kategorik (jenis_makanan)
df_encoded = pd.get_dummies(df, columns=["jenis_makanan"])

X = df_encoded.drop(columns=["status_kelayakan"])
y = df_encoded["status_kelayakan"]

# 3. Split Dataset 80:20 (Proposal Hal. 11)
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.20, random_state=42
)

# 4. Melatih Model Random Forest (Proposal Hal. 11)
model = RandomForestClassifier(n_estimators=100, random_state=42) 
model.fit(X_train, y_train)

# 5. Evaluasi Hasil
y_pred = model.predict(X_test)
print("=== METRIKS EVALUASI MODEL AI iFOOX ===")
print(classification_report(y_test, y_pred))

# 6. Simpan Model (Dilengkapi Otomatisasi Pembuatan Folder)
os.makedirs("model", exist_ok=True)  # Memastikan folder 'model' selalu ada
joblib.dump(model, "model/model_ifoox_rf.pkl")
print("✅ Model berhasil disimpan ke model/model_ifoox_rf.pkl")