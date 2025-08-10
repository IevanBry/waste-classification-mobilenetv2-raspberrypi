import os
import shutil
import argparse
from sklearn.model_selection import train_test_split

def get_all_files_recursive(source):
    file_paths = []
    for root, _, files in os.walk(source):
        for file_name in files:
            file_paths.append(os.path.join(root, file_name))
    return file_paths

def copy_files(file_list, source, destination, category):
    for file_path in file_list:
        category_path = os.path.join(destination, category, os.path.basename(file_path))
        os.makedirs(os.path.dirname(category_path), exist_ok=True)
        shutil.copy(file_path, category_path)
        print(f"Copied {file_path} to {category_path}")

def main():
    parser = argparse.ArgumentParser(description="Split dataset into train, val, and test folders with categories")
    parser.add_argument("--source", type=str, required=True, help="Path to source directory")
    parser.add_argument("--train_dest", type=str, required=True, help="Path to train destination directory")
    parser.add_argument("--val_dest", type=str, required=True, help="Path to validation destination directory")
    parser.add_argument("--test_dest", type=str, required=True, help="Path to test destination directory")
    parser.add_argument("--train_ratio", type=float, default=0.7, help="Proportion of train data (default: 0.7)")
    parser.add_argument("--val_ratio", type=float, default=0.15, help="Proportion of validation data (default: 0.15)")
    parser.add_argument("--random_state", type=int, default=42, help="Random seed for reproducibility (default: 42)")

    args = parser.parse_args()

    if args.train_ratio + args.val_ratio > 1.0:
        raise ValueError("Train ratio + validation ratio must be less than or equal to 1.0")

    test_ratio = 1.0 - (args.train_ratio + args.val_ratio)

    categories = [d for d in os.listdir(args.source) if os.path.isdir(os.path.join(args.source, d))]

    for category in categories:
        category_path = os.path.join(args.source, category)
        all_files = get_all_files_recursive(category_path)

        train_files, temp_files = train_test_split(
            all_files,
            train_size=args.train_ratio,
            random_state=args.random_state
        )

        val_ratio_adjusted = args.val_ratio / (args.val_ratio + test_ratio)
        val_files, test_files = train_test_split(
            temp_files,
            train_size=val_ratio_adjusted,
            random_state=args.random_state
        )

        copy_files(train_files, args.source, args.train_dest, category)
        copy_files(val_files, args.source, args.val_dest, category)
        copy_files(test_files, args.source, args.test_dest, category)

    print("Data splitting process completed.")

if __name__ == "__main__":
    main()