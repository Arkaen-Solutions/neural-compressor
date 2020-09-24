from ..metric import METRICS
from ..data import DATASETS, TRANSFORMS, DataLoader
from collections import OrderedDict
import copy

def update_config(new_cfg, default_cfg):
    if new_cfg is None:
        return default_cfg
    elif default_cfg is None:
        return new_cfg

    assert isinstance(new_cfg, dict) and isinstance(default_cfg, dict),\
        'new config and default conifg should be dict'
    return merge_dict(OrderedDict(new_cfg), default_cfg)

def merge_dict(new_dict, default_dict, branch=None):
    if branch is None:
        branch = []
    for key in default_dict.keys():
        if key in new_dict.keys():
            if isinstance(default_dict[key], dict) and \
               isinstance(new_dict[key], dict):
                merge_dict(new_dict[key], default_dict[key], branch + [str(key)])
        else:
            new_dict[key] = default_dict[key]
    return new_dict

    
def get_func_from_config(func_dict, cfg, compose=True):
    func_list = []
    for func_name, func_value in OrderedDict(cfg).items():
        func_kwargs = {}
        func_args = []
        if isinstance(func_value, dict):
            func_kwargs = func_value
        elif func_value is not None:
            func_args.append(func_value)
        func_list.append(func_dict[func_name](*func_args, **func_kwargs))

    func = func_dict['Compose'](func_list) if compose else \
        (func_list[0] if len(func_list) > 0 else None)
    return func


def get_preprocess(preprocesses, cfg, compose=True):
    return get_func_from_config(preprocesses, cfg, compose)


def get_metrics(metrics, cfg, compose=True):
    return get_func_from_config(metrics, cfg, compose)


def get_postprocess(postprocesses, cfg, compose=True):
    return get_func_from_config(postprocesses, cfg, compose)

def create_dataset(framework, data_source, cfg_preprocess):
    transform_list = []
    # generate framework specific transforms
    preprocesses = TRANSFORMS(framework, 'preprocess')

    preprocess = get_preprocess(preprocesses, cfg_preprocess)
    # even we can unify transform, how can we handle the IO, or we do the transform here
    datasets = DATASETS(framework)
    dataset_type = data_source.pop("type")
    # in this case we should prepare eval_data and calib_data sperately
    dataset = datasets[dataset_type](**data_source, transform=preprocess)
    return dataset

def create_dataloader(framework, dataloader_cfg):

    batch_size = int(dataloader_cfg['batch_size']) \
        if dataloader_cfg.get('batch_size') is not None else 1

    eval_dataset = create_dataset(framework,
                                  copy.deepcopy(dataloader_cfg['dataset']),
                                  copy.deepcopy(dataloader_cfg['transform']))

    return DataLoader(dataset=eval_dataset, framework=framework, batch_size=batch_size)

def create_eval_func(framework, dataloader, adaptor, metric_cfg, postprocess_cfg=None):
    """The interface to create evaluate function from config.

    Args:
        model (object): The model to be evaluated.

    Returns:
        Objective: The objective value evaluated
    """

    # eval_func being None means user will provide dataloader and metric info
    # in config yaml file
    assert dataloader, "dataloader should NOT be empty when eval_func is None"
    postprocess = None
    if postprocess_cfg is not None:
        postprocesses = TRANSFORMS(framework, "postprocess")
        postprocess = get_postprocess(postprocesses, postprocess_cfg.transform)

    if metric_cfg is not None:
        assert len(metric_cfg) == 1, "Only one metric should be specified!"
        metrics = METRICS(framework)
        # if not do compose will only return the first metric
        metric = get_metrics(metrics, metric_cfg, compose=False)
    else:
        metric = None
    
    def eval_func(model, measurer=None):
        return adaptor.evaluate(model, dataloader, postprocess, metric, measurer)

    return eval_func

