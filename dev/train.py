#!/usr/bin/env python3

import argparse
import csv
import shutil
import tomllib
import torch

from data.dataset import PointCloudDataset
from datetime import datetime
from model.regressor import Regressor
from pathlib import Path
from training.optimizer import build_optimizer
from training.loop import train_one_epoch, test_one_epoch
from training.loss import CustomLoss
from torch.utils.data import DataLoader


parser = argparse.ArgumentParser(description="Training pipeline")
parser.add_argument("train_data", help="path to Parquet training data")
parser.add_argument("val_data", help="path to Parquet validation data")
parser.add_argument("config", help="path to TOML config file")
parser.add_argument(
    "--output-dir", type=Path, help="output directory (default: YYYY_MM_DDTHH-MM-SS)"
)
parser.add_argument(
    "--force", action="store_true", help="overwrite OUTPUT_DIR if it already exists"
)

args = parser.parse_args()
if args.output_dir is None:
    args.output_dir = Path(datetime.now().strftime("%Y_%m_%dT%H-%M-%S"))

if args.output_dir.exists() and not args.force:
    raise FileExistsError(
        f"Output directory `{args.output_dir}` already exists. Use --force to overwrite."
    )
args.output_dir.mkdir(parents=True, exist_ok=True)

config = tomllib.load(open(args.config, "rb"))
shutil.copyfile(args.config, args.output_dir / "config.toml")

batch_size = config["training"]["batch_size"]
num_epochs = config["training"]["num_epochs"]
train_dataset = PointCloudDataset(args.train_data, config["data"])
validation_dataset = PointCloudDataset(args.val_data, config["data"])
model = Regressor(config["model"])
loss_fn = CustomLoss(config["training"]["loss"])
optimizer = build_optimizer(model.parameters(), config["training"]["optimizer"])


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

model.to(device)
train_dataloader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
validation_dataloader = DataLoader(validation_dataset, batch_size=batch_size)

training_log = args.output_dir / "training_log.csv"
with open(training_log, mode="w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["epoch", "training_loss", "validation_loss"])

best_loss = float("inf")
for i in range(num_epochs):
    train_loss = train_one_epoch(train_dataloader, model, loss_fn, optimizer, device)
    validation_loss = test_one_epoch(validation_dataloader, model, loss_fn, device)

    with open(training_log, mode="a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([i, train_loss, validation_loss])

    if validation_loss < best_loss:
        best_loss = validation_loss

        model_scripted = torch.jit.script(model)
        model_scripted.save(args.output_dir / "model.pt")
