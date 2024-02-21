import pybuda
import onnx 

import os
import requests
from PIL import Image
import pytest

from transformers import AutoImageProcessor

from pybuda.verify.backend import verify_module
from pybuda import VerifyConfig
from pybuda.verify.config import TestKind

def get_sample_data(model_name):
    url = "http://images.cocodataset.org/val2017/000000039769.jpg"
    image = Image.open(requests.get(url, stream=True).raw)

    image_processor = AutoImageProcessor.from_pretrained(model_name)
    pixel_values = image_processor(images=image, return_tensors="pt").pixel_values
    return pixel_values
        
@pytest.mark.parametrize("model_name", ["deepmind/vision-perceiver-conv", "deepmind/vision-perceiver-learned"])
def test_perceiver_for_image_classification_onnx(test_device, model_name):

    # Set PyBuda configuration parameters
    compiler_cfg = pybuda.config._get_global_compiler_config()
    compiler_cfg.balancer_policy = "Ribbon"
    compiler_cfg.enable_t_streaming = True
    compiler_cfg.default_df_override = pybuda.DataFormat.Float16_b
    compiler_cfg.enable_auto_fusing = False
    os.environ["PYBUDA_RIBBON2"]="1"
    os.environ["PYBUDA_FORCE_EMULATE_HARVESTED"]="1"
    os.environ["ARCH_NAME"]="wormhole_b0"
    
    if model_name == "deepmind/vision-perceiver-learned":
        os.environ["TT_BACKEND_OVERLAY_MAX_EXTRA_BLOB_SIZE"] = f"{105*1024}"
        
    elif model_name == "deepmind/vision-perceiver-conv":
        os.environ["TT_BACKEND_OVERLAY_MAX_EXTRA_BLOB_SIZE"] = f"{10*1024}"
        compiler_cfg.balancer_op_override("multiply_19", "t_stream_shape", (1,1))
        compiler_cfg.balancer_op_override("multiply_3103", "t_stream_shape", (1,1))
        compiler_cfg.balancer_op_override("multiply_3123", "t_stream_shape", (1,1))

    onnx_model_path = "pybuda/test/model_demos/utils/cnn/onnx/weights/perceiver/" + str(model_name.split("/")[-1]) + "/"+ "model.onnx"
    
    # Sample Image
    pixel_values = get_sample_data(model_name)

    # Load the onnx model
    onnx_model = onnx.load(onnx_model_path)
    onnx.checker.check_model(onnx_model)
    print("model loaded")
        
    # Create PyBuda module from Onnx model
    tt_model = pybuda.OnnxModule(str(model_name.split("/")[-1].replace("-","_"))+"_onnx",onnx_model,onnx_model_path)
    
    # Run inference on Tenstorrent device
    verify_module(
        tt_model,
        input_shapes=(pixel_values.shape,),
        inputs=[(pixel_values,)],
        verify_cfg=VerifyConfig(
            arch=test_device.arch,
            devtype=test_device.devtype,
            devmode=test_device.devmode,
            test_kind=TestKind.INFERENCE,
            pcc=0.96,
        )
    )
        