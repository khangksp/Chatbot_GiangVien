import pandas as pd

try:
    df = pd.read_csv('QA.csv')

    print(df.columns.tolist())

    print(df.shape)

    print(df.head(10))
    print(df.isnull().sum())

    total = len(df)
    print(f"Tổng số dòng trong DataFrame: {total}")
    
except FileNotFoundError:
    print("❌ Không tìm thấy file QA.csv")
except Exception as e:
    print(f"⚠️ Có lỗi xảy ra: {e}")
