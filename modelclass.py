from transformers import AutoModelForSequenceClassification, AutoTokenizer
import transformers
import torch
from sklearn.metrics import accuracy_score, recall_score, precision_score, f1_score
from transformers import TrainingArguments, Trainer
from scipy.stats import spearmanr
from sklearn.metrics import matthews_corrcoef
import numpy as np
import logging
import os
dir = os.path.dirname(os.path.abspath(__file__))
from transformers import set_seed

class Dataset(torch.utils.data.Dataset):
        def __init__(self, encodings, labels):
            self.encodings = encodings
            self.labels = labels

        def __getitem__(self, idx):
            item = {key: torch.tensor(val[idx]) for key, val in self.encodings.items()}
            item['labels'] = torch.tensor(self.labels[idx])
            return item

        def __len__(self):
            return len(self.labels)

def compute_metrics(eval_pred):
    # make differentiation between binary and multi-class classification
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)
    if len(np.unique(labels)) == 2:
        return {
            "Accuracy: " : accuracy_score(labels, predictions),
            "F1: " : f1_score(labels, predictions, pos_label=1), 
            "Precision_1: " : recall_score(labels, predictions, pos_label=1),
            "Recall_1: " : precision_score(labels, predictions, pos_label=1),
            "Precision_0: " : recall_score(labels, predictions, pos_label=0),
            "Recall_0: " : precision_score(labels, predictions, pos_label=0),
            # methew's correlation coefficient
            "Correlation: ": matthews_corrcoef(labels, predictions),
        }
    elif len(np.unique(labels)) >= 5:
        predictions = np.squeeze(predictions)
        return { #spearman correlation
            "Correlation: ": spearmanr(labels, predictions)[0],
        }
    else:
        return {
            "Accuracy: " : accuracy_score(labels, predictions),
            "F1: " : f1_score(labels, predictions, average="macro"), 
            "Precision: " : recall_score(labels, predictions, average="macro"),
            "Recall: " : precision_score(labels, predictions, average="macro"),
        }

def set_seed(seed=109):
    # set seed
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    transformers.set_seed(seed)

# Class representing a model
class ModelClass:
    def __init__(self, model_name, local, model_path, num_labels, seed=109):
        # init a huggingface auto model based on the model name
        if local:
            self.model = AutoModelForSequenceClassification.from_pretrained(model_path, local_files_only=local, num_labels=num_labels).to("cuda")
        else:
            set_seed(seed)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_name, local_files_only=local, num_labels=num_labels).to("cuda")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

    def predict(self, texts, bs = 128):
        predictions = self.predictor(texts, bs).tolist()
        return np.argmax(predictions, axis=1)

    def predictor(self, texts, bs = 128):
        if isinstance(texts, str):
            texts = [texts]

        predictions = []
        with torch.no_grad():
            self.model.eval()
            if type(texts) is not tuple:
                break_len = len(texts)
            else:
                break_len = len(texts[0])

            for i in range(0, break_len, bs):
                if type(texts) is not tuple:
                    batch_x = self.tokenizer(texts[i:i+bs], padding=True, truncation=True, return_tensors="pt").to("cuda")
                else:
                    batch_x = self.tokenizer(texts[0][i:i+bs], texts[1][i:i+bs], padding=True, truncation=True, return_tensors="pt").to("cuda")
                predictions.extend(torch.nn.functional.softmax(self.model(**batch_x)[0], dim=1).cpu().detach().tolist())
        return np.array(predictions)

    def train(self, x_train, y_train, x_dev, y_dev, train_bs = 8, test_bs = 32):
        if type(x_train) is not tuple:
            train_encodings = self.tokenizer(x_train, padding=True, truncation=True, return_tensors="pt")
            dev_encodings = self.tokenizer(x_dev, padding=True, truncation=True, return_tensors="pt")
        else:
            train_encodings = self.tokenizer(*x_train, padding=True, truncation=True, return_tensors="pt")
            dev_encodings = self.tokenizer(*x_dev, padding=True, truncation=True, return_tensors="pt")

        train_dataset = Dataset(train_encodings, y_train)
        test_dataset = Dataset(dev_encodings, y_dev)

        training_args = TrainingArguments(
            output_dir='./results',          # output directory
            num_train_epochs=25,              # total number of training epochs
            per_device_train_batch_size=train_bs,  # batch size per device during training
            per_device_eval_batch_size=test_bs,   # batch size for evaluation
            warmup_steps=5,                # number of warmup steps for learning rate scheduler
            weight_decay=0.01,               # strength of weight decay
            logging_dir='./logs',            # directory for storing logs
            logging_steps=1000,
            eval_steps=100,
        )

        trainer = Trainer(
            model=self.model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=test_dataset,
            compute_metrics=compute_metrics,
        )

        trainer.train()
        # logging the results
        logging.info("Training results:")
        evaluations = trainer.evaluate()

        logging.info(evaluations)

        return evaluations

    def evaluate(self, x_test, y_test):
        if type(x_test) is not tuple:
            test_encodings = self.tokenizer(x_test, padding=True, truncation=True, return_tensors="pt")
        else:
            test_encodings = self.tokenizer(*x_test, padding=True, truncation=True, return_tensors="pt")

        test_dataset = Dataset(test_encodings, y_test)
        trainer = Trainer(
            model=self.model,
            compute_metrics=compute_metrics,
        )
        logging.info("Test results:")
        logging.info(trainer.evaluate(test_dataset))


    def save(self, path):
        self.model.save_pretrained(path)

    def load(self, path, num_labels):
        self.model = AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True, num_labels=num_labels)
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
