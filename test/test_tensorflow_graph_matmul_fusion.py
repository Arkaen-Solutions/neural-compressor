#
#  -*- coding: utf-8 -*-
#
import os
import unittest
import yaml
import numpy as np
import tensorflow.compat.v1 as tf
from tensorflow.core.framework import graph_pb2
from tensorflow.python.framework import dtypes
from ilit.adaptor.tf_utils.quantize_graph.quantize_graph_common import QuantizeGraphHelper
from ilit.adaptor.tf_utils.quantize_graph.quantize_graph_matmul import FuseNodeStartWithMatmul
from ilit.adaptor.tensorflow import TensorflowQuery

def build_fake_yaml():
    fake_yaml = '''
        model:
          name: fake_yaml
          framework: tensorflow
          inputs: x
          outputs: op_to_store
        device: cpu
        evaluation:
          accuracy:
            metric:
              topk: 1
        tuning:
            strategy:
              name: basic
            accuracy_criterion:
              relative: 0.01
            workspace:
              path: saved
        '''
    y = yaml.load(fake_yaml, Loader=yaml.SafeLoader)
    with open('fake_yaml.yaml', "w", encoding="utf-8") as f:
        yaml.dump(y, f)
    f.close()


class TestGraphMatMulFusion(unittest.TestCase):

    @classmethod
    def setUpClass(self):
        build_fake_yaml()
        self.op_wise_sequences = TensorflowQuery(local_config_file=os.path.join(
            os.path.dirname(__file__), "../ilit/adaptor/tensorflow.yaml")).get_eightbit_patterns()
    @classmethod
    def tearDownClass(self):
        os.remove('fake_yaml.yaml')

    def test_matmul_biasadd_relu_fusion(self):
        tf.disable_eager_execution()

        input_constant_name = "input_constant"
        relu_name = "relu"
        float_graph_def = graph_pb2.GraphDef()
        input_constant = QuantizeGraphHelper.create_constant_node(
            input_constant_name,
            value=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            dtype=dtypes.float32,
            shape=[1, 2, 6, 1])
        float_graph_def.node.extend([input_constant])
        relu_node = QuantizeGraphHelper.create_node("Relu", relu_name,
                                                    [input_constant_name])
        QuantizeGraphHelper.set_attr_dtype(relu_node, "T", dtypes.float32)
        float_graph_def.node.extend([relu_node])

        b_constant_name = "b_constant"
        mat_mul_name = "mat_mul"

        b_constant = QuantizeGraphHelper.create_constant_node(
            b_constant_name, value=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], dtype=dtypes.float32, shape=[2, 6])
        float_graph_def.node.extend([b_constant])

        mat_mul_node = QuantizeGraphHelper.create_node("MatMul", mat_mul_name,
                                                       [relu_name, b_constant_name])
        QuantizeGraphHelper.set_attr_dtype(mat_mul_node, "T", dtypes.float32)
        QuantizeGraphHelper.set_attr_bool(mat_mul_node, "transpose_a", False)
        QuantizeGraphHelper.set_attr_bool(mat_mul_node, "transpose_b", False)
        float_graph_def.node.extend([mat_mul_node])

        bias_add_name = "bias_add"
        offset_constant_name = "offset_constant"

        offset_constant = QuantizeGraphHelper.create_constant_node(
            offset_constant_name,
            value=[1, 2, 3, 4, 5, 6],
            dtype=dtypes.float32,
            shape=[6])
        float_graph_def.node.extend([offset_constant])
        bias_add_node = QuantizeGraphHelper.create_node(
            "BiasAdd", bias_add_name, [mat_mul_name, offset_constant_name])
        QuantizeGraphHelper.set_attr_dtype(bias_add_node, "T", dtypes.float32)
        float_graph_def.node.extend([bias_add_node])

        post_relu_name = "post_relu"
        post_relu_node = QuantizeGraphHelper.create_node("Relu", post_relu_name,
                                                         [bias_add_name])
        float_graph_def.node.extend([post_relu_node])

        worker = FuseNodeStartWithMatmul(
            float_graph_def, mat_mul_name, self.op_wise_sequences['MatMul'],
            False, mat_mul_name, 'cpu', False)
        output_graph = worker.apply_the_transform()
        found_quantized_matmul = False
        for i in output_graph.node:
            if i.op == 'QuantizedMatMulWithBiasAndRelu':
                found_quantized_matmul = True
                break

        self.assertEqual(found_quantized_matmul, True)

    def test_matmul_biasadd_relu_requantize_fusion(self):
        tf.disable_v2_behavior()
        g = tf.Graph()
        with g.as_default():
            from ilit import Quantization

            x_data = np.array([[0.1, 0.2], [0.2, 0.3]])
            y_data = np.array([[1, 2], [3, 4]], dtype=np.float)
            x = tf.placeholder(tf.float32, shape=[2, 2], name='x')
            y = tf.constant(y_data, dtype=tf.float32, shape=[2, 2])
            z = tf.matmul(x, y)
            z = tf.nn.bias_add(z, [1, 2])
            z = tf.nn.relu(z, name='op_to_store')
            found_quantized_matmul = False
            with tf.Session() as sess:
                sess.run(z, feed_dict={x: x_data, y: y_data})
                float_graph_def = sess.graph.as_graph_def()

                quantizer = Quantization('fake_yaml.yaml')
                dataset = quantizer.dataset('dummy', shape=(2, 2), label=True)
                dataloader = quantizer.dataloader(dataset, batch_size=2)
                output_graph = quantizer(
                    float_graph_def,
                    q_dataloader=dataloader,
                    eval_dataloader=dataloader
                )
                for i in output_graph.as_graph_def().node:
                    if i.op == 'QuantizedMatMulWithBiasAndReluAndRequantize':
                        found_quantized_matmul = True
                        break
                self.assertEqual(found_quantized_matmul, True)

    def test_first_matmul_biasadd_relu_fusion(self):
        tf.disable_v2_behavior()

        x_data = np.array([[0.1, 0.2], [0.2, 0.3]])
        y_data = np.array([[1, 2], [3, 4]], dtype=np.float)
        x = tf.placeholder(tf.float32, shape=[2, 2])
        y = tf.constant(y_data, dtype=tf.float32, shape=[2, 2])
        z = tf.matmul(x, y)
        z = tf.nn.bias_add(z, [1, 2])
        z = tf.nn.relu(z)

        with tf.Session() as sess:
            sess.run(z, feed_dict={x: x_data, y: y_data})
            float_graph_def = sess.graph.as_graph_def()

            float_graph_def = QuantizeGraphHelper().get_sorted_graph(
                float_graph_def, ['Placeholder'], ['Relu'])

            worker = FuseNodeStartWithMatmul(
                float_graph_def, 'MatMul', self.op_wise_sequences['MatMul'], False, 'MatMul', 'cpu', True)
            output_graph = worker.apply_the_transform()

            found_quantized_matmul = False
            for i in output_graph.node:
                if i.op == 'QuantizeV2' and i.name == 'MatMul_eightbit_quantize_Placeholder' and i.attr["T"].type == dtypes.quint8:
                    found_quantized_matmul = True
                    break

            self.assertEqual(found_quantized_matmul, True)

    def test_matmul_biasadd_requantize_dequantize_fusion(self):
        tf.disable_v2_behavior()

        g = tf.Graph()
        with g.as_default():
            from ilit import Quantization

            x_data = np.array([[0.1, 0.2], [0.2, 0.3]])
            y_data = np.array([[1, 2], [3, 4]], dtype=np.float)
            x = tf.placeholder(tf.float32, shape=[2, 2], name='x')
            y = tf.constant(y_data, dtype=tf.float32, shape=[2, 2])
            z = tf.matmul(x, y)
            z = tf.nn.bias_add(z, [1, 2])
            z = tf.identity(z, name='op_to_store')
            found_quantized_matmul = False
            if tf.version.VERSION < "2.2.0":
                found_quantized_matmul = True
            else:
                with tf.Session() as sess:
                    sess.run(z, feed_dict={x: x_data, y: y_data})
                    float_graph_def = sess.graph.as_graph_def()

                    quantizer = Quantization('fake_yaml.yaml')
                    dataset = quantizer.dataset('dummy', shape=(2, 2), label=True)
                    dataloader = quantizer.dataloader(dataset, batch_size=2)
                    output_graph = quantizer(
                        float_graph_def,
                        q_dataloader=dataloader,
                        eval_dataloader=dataloader
                    )

                    for i in output_graph.as_graph_def().node:
                        if i.op == 'QuantizedMatMulWithBiasAndDequantize':
                            found_quantized_matmul = True
                            break
            self.assertEqual(found_quantized_matmul, True)

if __name__ == '__main__':
    unittest.main()
