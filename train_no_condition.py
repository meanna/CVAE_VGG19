import os
import time
from ast import literal_eval
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torchvision.datasets as Datasets
import torchvision.models as models
import torchvision.transforms as T
import torchvision.utils as vutils
from torch.utils.data import Dataset, DataLoader
from tqdm.notebook import trange, tqdm

from RES_VAE0 import VAE
from vgg19 import VGG19

# ---------------------------------------------------------------
date_time_obj = datetime.now()
timestamp_str = date_time_obj.strftime("%Y-%m-%d_%H.%M.%S")
print('Current Timestamp : ', timestamp_str)
start_time_total = time.perf_counter()
# ---------------------------------------------------------------
# Parameter you can change

batch_size = 128
num_epoch = 1
# Available datasets: celeba_small, celeba
dataset = "celeba_small"  # < --------------change this!
print("dataset = ", dataset)
latent_dim = 128  # < --------------change this!

# Checkpoint os pretrained models
# "CNN_VAE_celeba_small_2022-08-04_21.40.10" (small, for testing)
# "CNN_VAE_celeba_2022-08-04_18.05.43" (large model trained for 20 epochs)
# "celebA_64_8_epoch_latent_dim_128"
# "CNN_VAE_celeba_2022-08-04_23.22.32" (add condition to layer 4, trained for 10 epochs, good result, latent = 128) RES_VAE2, run2
# CNN_VAE_celeba_2022-08-05_01.49.10 #(VAE3) (add condition to layer 5)
# CNN_VAE_celeba_2022-08-05_03.20.52  #python run2.py (add condition to layer 4)  VAE2 , latent dim = 128
# CNN_VAE_celeba_2022-08-05_11.31.54 # run2.py (add condition to layer 4)  VAE2, latent dim = 512 (quality not good, 10 epoch)

#continue training  "CNN_VAE_celeba_2022-08-04_23.22.32" for 10 epochs, ...

# !! no "pt"
# set to None if you do not want to load a checkpoint
#
load_checkpoint = None
run_train = True

# logging
if run_train and load_checkpoint:
    print("Train with pretrained model...")
elif run_train and load_checkpoint is None:
    print("Train from scratch...")
elif load_checkpoint is not None and not run_train:
    print("Only load pretrained model, do not train...")
elif load_checkpoint is None and not run_train:
    #print("Set run_train to True or give a checkpoint")
    raise SystemExit("!Set run_train to True or give a checkpoint...")


# ---------------------------------------------------------------
# Parameters you may NOT want to change
condition_dim = 512
image_size = 64
lr = 1e-4
start_epoch = 0
dataset_root = "./input/"
save_dir = os.getcwd()
beta = 0.1

# ---------------------------------------------------------------
use_cuda = torch.cuda.is_available()
GPU_indx = 0
device = torch.device(GPU_indx if use_cuda else "cpu")

# ---------------------------------------------------------------
if load_checkpoint:
    model_name = load_checkpoint
else:
    model_name = f"CNN_VAE_{dataset}_{timestamp_str}"  # "STL10_8" #"STL10_8" #STL10_8_64.pt


# ---------------------------------------------------------------
class CelebA_CLIP(Datasets.ImageFolder):
    def __init__(
            self,
            root,
            transform,
            image_folder,
            clip_embeddings_csv
    ):
        super(CelebA_CLIP, self).__init__(
            root=root,
            transform=transform
        )

        self.clip_embeddings = clip_embeddings_csv
        self.samples = self.make_dataset_(root, None, None, None)
        self.root = os.path.join(root, image_folder)

    def __len__(self) -> int:
        return len(self.samples)

    def make_dataset_(self, root, class_to_idx, extensions, is_valid_file):
        df = pd.read_csv(self.clip_embeddings, index_col=0,
                         converters={'embeddings': literal_eval})
        im_names = df['image_id'].values
        # img_embed = zip(df['image_id'].values, df["embeddings"].values)
        # img_embed = tuple(zip(range(len(im_names)), im_names, df["embeddings"].values))
        targets = df["embeddings"].values  # <class 'numpy.ndarray'> #(batch,)
        img_embed = tuple(zip(im_names, targets))

        return list(img_embed)

    def __getitem__(self, index):
        """
        Args:
            index (int): Index

        Returns:
            tuple: (sample, target) where target is class_index of the target class.
        """
        # print(len(self.samples))
        # print("index,", index)
        path, target = self.samples[index]
        # print("path", path)
        path = os.path.join(self.root, path)
        # print("path", path)

        sample = self.loader(path)
        if self.transform is not None:
            sample = self.transform(sample)

        target = torch.tensor(target)

        return sample, target


# ---------------------------------------------------------------
def get_data_STL10(transform, batch_size, download=True, root="./input"):
    print("Loading trainset...")
    trainset = Datasets.STL10(root=root, split='unlabeled', transform=transform, download=download)

    trainloader = DataLoader(trainset, batch_size=batch_size, shuffle=True, num_workers=2)

    print("Loading testset...")
    testset = Datasets.STL10(root=root, split='test', download=download, transform=transform)

    testloader = DataLoader(testset, batch_size=batch_size, shuffle=False, num_workers=2)
    print("Done!")

    return trainloader, testloader


def get_data_celebA(transform, batch_size, download=False, root="/data"):
    # data_root = "../../datasets/celeba_small/celeba/"
    data_root = "../../datasets/resized_celebA2/"
    training_data = CelebA_CLIP(root=data_root,
                                transform=transform,
                                image_folder="celebA",
                                clip_embeddings_csv="./embeddings.csv")
    print("dataset size", len(training_data))  # 202599
    test_size = 16
    train_size = len(training_data) - test_size
    trainset, testset = torch.utils.data.random_split(training_data, [train_size, test_size])

    trainloader = DataLoader(trainset, batch_size=batch_size, shuffle=True, num_workers=8)
    testloader = DataLoader(testset, batch_size=batch_size, shuffle=False, num_workers=8)
    print("Done load dataset")
    return trainloader, testloader, train_size


def get_data_celebA_small(transform, batch_size, download=False, root="/data"):
    data_root = "./datasets/celeba_small/celeba/"
    training_data = CelebA_CLIP(root=data_root,
                                transform=transform,
                                image_folder="img_align_celeba",
                                clip_embeddings_csv="./embeddings_128.csv")

    print("dataset size", len(training_data))  # 128
    test_size = 16
    train_size = len(training_data) - test_size
    trainset, testset = torch.utils.data.random_split(training_data, [train_size, test_size])

    trainloader = DataLoader(trainset, batch_size=batch_size, shuffle=True, num_workers=8)
    testloader = DataLoader(testset, batch_size=batch_size, shuffle=False, num_workers=8)
    print("Done load dataset")
    return trainloader, testloader, train_size


# ---------------------------------------------------------------
if dataset == "celeba":
    # transform = T.Compose([T.CenterCrop(178),T.Resize((image_size,image_size)), T.ToTensor()])
    # transform = T.Compose([T.Resize((image_size,image_size)), T.ToTensor()])
    transform = T.Compose([T.Resize(image_size), T.ToTensor()])
    trainloader, testloader, train_size = get_data_celebA(transform, batch_size, download=True, root=dataset_root)
elif dataset == "celeba_small":
    transform = T.Compose([T.CenterCrop(178), T.Resize((image_size, image_size)), T.ToTensor()])
    trainloader, testloader, train_size = get_data_celebA_small(transform, batch_size, download=True, root=dataset_root)
else:
    transform = T.Compose([T.Resize(image_size), T.ToTensor()])
    trainloader, testloader = get_data_STL10(transform, batch_size, download=True, root=dataset_root)

# ---------------------------------------------------------------
# get a test image batch from the testloader to visualise the reconstruction quality
dataiter = iter(testloader)
test_images, test_labels = dataiter.next()
print("load test batch")
print("image input shape", test_images.shape)
print("condition shape", test_labels.shape)  # torch.Size([16, 1, 512])


# ---------------------------------------------------------------
# OLD way of getting features and calculating loss - Not used

# create an empty layer that will simply record the feature map passed to it.
class GetFeatures(nn.Module):
    def __init__(self):
        super(GetFeatures, self).__init__()
        self.features = None

    def forward(self, x):
        self.features = x
        return x


# download the pre-trained weights of the VGG-19 and append them to an array of layers .
# we insert a GetFeatures layer after a relu layer.
# layers_deep controls how deep we go into the network
def get_feature_extractor(layers_deep=7):
    C_net = models.vgg19(pretrained=True).to(device)
    C_net = C_net.eval()

    layers = []
    for i in range(layers_deep):
        layers.append(C_net.features[i])
        if isinstance(C_net.features[i], nn.ReLU):
            layers.append(GetFeatures())
    return nn.Sequential(*layers)


# this function calculates the L2 loss (MSE) on the feature maps copied by the layers_deep
# between the reconstructed image and the origional
def feature_loss(img, recon_data, feature_extractor):
    img_cat = torch.cat((img, torch.sigmoid(recon_data)), 0)
    out = feature_extractor(img_cat)
    loss = 0
    for i in range(len(feature_extractor)):
        if isinstance(feature_extractor[i], GetFeatures):
            loss += (feature_extractor[i].features[:(img.shape[0])] - feature_extractor[i].features[
                                                                      (img.shape[0]):]).pow(2).mean()
    return loss / (i + 1)


# Linear scaling the learning rate down
def lr_Linear(epoch_max, epoch, lr):
    lr_adj = ((epoch_max - epoch) / epoch_max) * lr
    set_lr(lr=lr_adj)


def set_lr(lr):
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


def vae_loss(recon, x, mu, logvar):
    recon_loss = F.binary_cross_entropy_with_logits(recon, x)
    KL_loss = -0.5 * (1 + logvar - mu.pow(2) - logvar.exp()).mean()
    loss = recon_loss + 0.01 * KL_loss
    return loss


# ---------------------------------------------------------------

# Create the feature loss module

# load the state dict for vgg19
state_dict = torch.hub.load_state_dict_from_url('https://download.pytorch.org/models/vgg19-dcbb9e9d.pth')
# manually create the feature extractor from vgg19
feature_extractor = VGG19(channel_in=3)

# loop through the loaded state dict and our vgg19 features net,
# loop will stop when net.parameters() runs out - so we never get to the "classifier" part of vgg
for ((name, source_param), target_param) in zip(state_dict.items(), feature_extractor.parameters()):
    target_param.data = source_param.data
    target_param.requires_grad = False

feature_extractor = feature_extractor.to(device)

# ---------------------------------------------------------------

# Create the save directory if it does note exist
if not os.path.isdir(save_dir + "/Models"):
    os.makedirs(save_dir + "/Models")
if not os.path.isdir(save_dir + "/Results"):
    os.makedirs(save_dir + "/Results")

result_folder = os.path.join(save_dir, "Results", f"result_{model_name}")
if not os.path.exists(result_folder):
    os.mkdir(result_folder)

# ---------------------------------------------------------------
# Load / Initialize the model
model_save_path = os.path.join(save_dir, "Models", model_name + ".pt")



if load_checkpoint:

    if model_name == "CNN_VAE_celeba_2022-08-04_18.05.43":
        batch_size = 128
        condition_dim = 512
        latent_dim = 512
        checkpoint = torch.load(save_dir + "/Models/" + model_name + ".pt", map_location="cpu")
        print("Checkpoint loaded")
        vae_net = VAE(channel_in=3 + condition_dim, ch=64, z=latent_dim, condition_dim=condition_dim).to(device)
        optimizer = optim.Adam(vae_net.parameters(), lr=lr, betas=(0.5, 0.999))
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        vae_net.load_state_dict(checkpoint['model_state_dict'])
        start_epoch = checkpoint["epoch"]
        loss_log = checkpoint["loss_log"]

    else:
        vae_net = torch.load(model_save_path)

elif run_train:
    # If checkpoint does exist raise an error to prevent accidental overwriting
    if os.path.isfile(model_save_path):
        # raise ValueError("Warning Checkpoint exists")
        print("Warning Checkpoint exists")

    # Create VAE network
    # z = latent dim, ch = out channel
    print("Initialize VAE net ...")
    vae_net = VAE(channel_in=3, ch=64, z=latent_dim).to(device)

# setup optimizer
optimizer = optim.Adam(vae_net.parameters(), lr=lr, betas=(0.5, 0.999))
# Loss function
BCE_Loss = nn.BCEWithLogitsLoss()

# ---------------------------------------------------------------
def convert_batch_to_image_grid(image_batch, dim=64):
    print("image_batch", image_batch.shape)
    # torch.Size([16, 3, 64, 64])
    reshaped = (image_batch.reshape(4, 8, dim, dim, 3)
                .transpose(0, 2, 1, 3, 4)
                .reshape(4 * dim, 8 * dim, 3))
    return reshaped


import torchvision


def show_image_grid(img_tensor, save_path):
    grid_img = torchvision.utils.make_grid(img_tensor.cpu())
    plt.figure(figsize=(20, 20))
    plt.imshow(grid_img.permute(1, 2, 0))
    plt.axis('off')
    plt.show()
    plt.savefig(os.path.join(save_path), dpi=200, bbox_inches='tight')


def save_each_image(img_tensor):
    img_tensor = img_tensor.detach()
    for i in range(img_tensor.shape[0]):
        img = img_tensor[i].permute(1, 2, 0)
        plt.imshow(img.numpy())
        im_name = 'img_{}.png'.format(i)
        plt.savefig(os.path.join(save_dir, "Results", im_name), dpi=200, bbox_inches='tight')



def image_generation():
    batch = 16
    latent_dim = vae_net.latent_dim
    # sample both initial input and condition
    mu = torch.zeros(batch, latent_dim , 1, 1) + 1.0
    log_var = torch.zeros(batch, latent_dim, 1, 1) + 0.3
    # # print(mu.shape)
    # zero_tensor = torch.zeros(batch, condition_dim, 1, 1).to(device)


    z = vae_net.encoder.sample(mu.to(device), log_var.to(device))
    #z_cond = torch.cat((z, zero_tensor), dim=1)
    # print("zcond",z_cond.shape) #zcond torch.Size([128, 512, 1, 1])
    logits = vae_net.decoder(z)
    generated = torch.sigmoid(logits)
    save_path = os.path.join(result_folder, "generation_zero.png")
    vutils.save_image(generated, save_path)
    print("save image at", save_path)
    save_path2 = os.path.join(result_folder, "generation_zero2.png")
    show_image_grid(generated, save_path2)


# ----------------------------------------------------------
def train():

    loss_log = []

    # save log
    with open(os.path.join(result_folder, "params.txt"), "w") as f:
        f.write(f"epoch = {num_epoch}\n")
        f.write(f"learning_rate = {lr}\n")
        f.write(f"train_size = {train_size}\n")
        f.write(f"batch_size = {batch_size} \n")
        f.write(f"label_dim = {condition_dim}\n")
        f.write(f"image_size = {image_size}\n")
        f.write(f"latent_dim = {latent_dim}\n")
        f.write(f"beta = {beta}\n")
        f.write(f"model checkpoint = {model_save_path}\n\n")

    for epoch in trange(start_epoch, num_epoch, leave=False):
        start_time_epoch = time.perf_counter()
        lr_Linear(num_epoch, epoch, lr)
        vae_net.train()
        for i, (images, _) in enumerate(tqdm(trainloader, leave=False)):
            images = images.to(device)
            #condition = condition.to(device)  # [batch, 512]
            # recon_data = [batch, 3 + 512, 64, 64]
            recon_data, mu, logvar = vae_net(images)

            # VAE loss
            loss = vae_loss(recon_data, images, mu, logvar)

            # Perception loss
            loss += feature_extractor(torch.cat((torch.sigmoid(recon_data), images), 0))

            loss_log.append(loss.item())
            vae_net.zero_grad()
            loss.backward()
            optimizer.step()

        # In eval mode the model will use mu as the encoding instead of sampling from the distribution
        print("epoch", epoch)
        exec_time_epoch = time.perf_counter() - start_time_epoch

        print(f"time epoch = {exec_time_epoch} sec ({exec_time_epoch / 60.0} min )\n")
        with open(os.path.join(result_folder, "params.txt"), "a") as f:
            f.write(f"\nepoch {epoch}, time epoch = {exec_time_epoch} sec ({exec_time_epoch / 60.0} min )\n")

        vae_net.eval()
        with torch.no_grad():
            recon_data, _, _ = vae_net(test_images.to(device))
            images = torch.cat((torch.sigmoid(recon_data.cpu()), test_images), 2)
            save_path = os.path.join(result_folder, "recon" + "_" + str(epoch) + ".png")
            # save_path = "%s/%s/%s_%d_%d.png" % (save_dir, "Results", model_name, image_size, epoch)
            # print(images.shape)  # [128, 3, 128, 64]
            print("save image at", save_path)
            vutils.save_image(images, save_path)

            # Save a checkpoint
            torch.save(vae_net, model_save_path)
            # torch.save({
            #     'epoch': epoch,
            #     'loss_log': loss_log,
            #     'model_state_dict': vae_net.state_dict(),
            #     'optimizer_state_dict': optimizer.state_dict()
            #
            # }, model_save_path)
            # torch.save(vae_net, model_save_path)
            print("Save checkpoint at", model_save_path)

    exec_time_total = time.perf_counter() - start_time_total
    print(f"time total = {exec_time_total} sec ({exec_time_total / 60.0} min )\n")
    with open(os.path.join(result_folder, "params.txt"), "a") as f:
        f.write(f"\ntime total = {exec_time_total} sec ({exec_time_total / 60.0} min )\n")


# ---------------------------------------------------------------
if __name__ == "__main__":
    if run_train:
        train()
    image_generation()

