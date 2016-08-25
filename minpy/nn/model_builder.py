import minpy.numpy as np
import minpy.core
import minpy.nn.layers as layers
from minpy.nn.model import ModelBase
import mxnet as mx

class Module(object):
    """ The base class of building blocks of neural networks. """

    def __init__(self):
        pass

    def parameter_shape(self, input_shape):
        """ Customized modules should override this function.

        :param tuple input_shape: The shape of one training sample, i.e. (3072,) or (3, 32, 32).
        :return: A dictionary mapping the names of parameters to their shapes.
        """
        return {}


class Parallel(Module):
    # TODO
    pass


class Sequential(Module):
    def __init__(self, *args):
        super(Sequential, self).__init__()
        if args:
            assert all(isinstance(arg, Module) for arg in args)
            self.__modules = list(args)
        else:
            self.__modules = []

    def forward(self, X, params):
        return reduce(
            lambda inputs, module : module.forward(inputs, params),
            self.__modules,
            X
        )

    def output_shape(self, input_shape):
        return reduce(
            lambda shape, module : module.output_shape(shape),
            self.__modules,
            input_shape
        )

    def parameter_shape(self, input_shape):
        shapes = {}
        def update_shapes(shape, module):
            shapes.update(module.parameter_shape(shape))
            return module.output_shape(shape)
        reduce(
            update_shapes,
            self.__modules,
            input_shape
        )
        return shapes

    def parameter_settings(self):
        settings = {}
        for module in self.__modules:
            try:
                settings.update(module.parameter_settings())
            except:
                pass
        return settings

    def append(self, module):
        assert isinstance(module, Module)
        self.__modules.append(module)

    def insert(self, index, module):
        assert isinstance(module, Module)
        self.__modules.insert(index, module)

    def remove(index):
        assert -1 < index and index < len(self.__modules)
        del self.__modules[index]


class Affine(Module):
    count = 0
    def __init__(self, hidden_number, initializer=None):
        super(Affine, self).__init__()
        self.hidden_number = hidden_number 
        self.weight = 'affine%d_weight' % self.__class__.count
        self.bias   = 'affine%d_bias' % self.__class__.count

        self.__class__.count += 1

    def forward(self, inputs, params):
        return layers.affine(inputs, params[self.weight], params[self.bias])

    def parameter_shape(self, input_shape):
        weight_shape = (input_shape[-1], self.hidden_number)
        bias_shape   = (self.hidden_number,)
        return {
            self.weight : weight_shape, 
            self.bias   : bias_shape 
        }

    def output_shape(self, input_shape):
        return (self.hidden_number,)
    
    def parameter_settings(self):
      return initializer if initializer else \
      {
          self.weight : {'init_rule' : 'xavier'},
          self.bias   : {'init_rule' : 'constant'}
      }
        

class BatchNormalization(Module):
    count = 0
    def __init__(self, epsilon=1e-5, momentum=0.9):
        super(BatchNormalization, self).__init__()
        self.epsilon  = epsilon
        self.momentum = momentum
        self.running_mean, self.running_variance = None, None

        self.gamma = 'BN%d_gamma' % self.__class__.count
        self.beta  = 'BN%d_beta' % self.__class__.count

        self.__class__.count += 1

    def forward(self, inputs, params):
        outputs, running_mean, running_variance = layers.batchnorm(
            inputs,
            params[self.gamma],
            params[self.beta],
            params['__training_in_progress__'],
            self.epsilon,
            self.momentum,
            self.running_mean,
            self.running_variance
        )
        self.running_mean, self.running_variance = running_mean, running_variance
        return outputs

    def output_shape(self, input_shape):
        return input_shape

    def parameter_shape(self, input_shape):
        return {
            self.gamma : input_shape,
            self.beta  : input_shape
        }

    def parameter_settings(self):
        return {
            self.gamma : {'init_rule' : 'constant', 'init_config' : {'value': 1.0}},
            self.beta  : {'init_rule' : 'constant'}
        }


class SpatialBatchNormalization(BatchNormalization):
    count = 0
    def __init__(self, epsilon=1e-5, momentum=0.9):
        super(SpatialBatchNormalization, self).__init__(epsilon=1e-5, momentum=0.9)
        self.gamma = 'SpatialBN%d_gamma' % self.__class__.count
        self.beta  = 'SpatialBN%d_beta' % self.__class__.count

    def forward(self, inputs, params):
        N, C, W, H = inputs.shape
        inputs = transpose(inputs, (0, 2, 3, 1))
        inputs = np.reshape(inputs, (N * W * H, C))

        outputs, running_mean, running_variance = layers.batchnorm(
            inputs,
            params[self.gamma],
            params[self.beta],
            params['__training_in_progress__'],
            self.epsilon,
            self.momentum,
            self.running_mean,
            self.running_variance
        )
        self.running_mean, self.running_variance = running_mean, running_variance
        outputs = np.reshape(outputs, (N, W, H, C))
        outputs = transpose(outputs, (0, 3, 1, 2)) 
        return outputs

    def output_shape(self, input_shape):
        return input_shape

    def parameter_shape(self, input_shape):
        return {
            self.gamma : (input_shape[0],),
            self.beta  : (input_shape[0],)
        }

    def parameter_settings(self):
        return {
            self.gamma : {'init_rule' : 'constant', 'init_config' : {'value': 1.0}},
            self.beta  : {'init_rule' : 'constant'}
        }


class Convolution(Module):
    count = 0
    def __init__(self, kernel_shape, kernel_number, stride=(1, 1), pad=(0, 0), initializer):
        super(Convolution, self).__init__()
        self.kernel_shape  = kernel_shape
        self.kernel_number = kernel_number
        self.stride        = stride
        self.pad           = pad

        self.weight = 'convolution%d_weight' % self.__class__.count
        self.bias   = 'convolution%d_bias' % self.__class__.count

        self.__class__.count += 1

        self.inputs = mx.sym.Variable(name='inputs')
        self.convolution = mx.sym.Convolution(
            name       = 'convolution',
            data       = self.inputs,
            kernel     = self.kernel_shape,
            num_filter = self.kernel_number,
            stride     = self.stride,
            pad        = self.pad
        )

    def forward(self, inputs, params):
        args = {
            'inputs'             : inputs,
            'convolution_weight' : params[self.weight],
            'convolution_bias'   : params[self.bias]
        }
        return minpy.core.Function(self.convolution, {'inputs':inputs.shape})(**args)

    def output_shape(self, input_shape):
        __, output_shape, __ = self.convolution.infer_shape(inputs=tuple([1] + list(input_shape)))
        return normal_shape(output_shape[0][1:])

    def parameter_shape(self, input_shape):
        assert len(input_shape) == 3, 'The input tensor should be 4D.'
        weight_shape = (self.kernel_number, input_shape[0], self.kernel_shape[0], self.kernel_shape[1])
        bias_shape   = (self.kernel_number,)
        return {
            self.weight : weight_shape, 
            self.bias   : bias_shape 
        }

    def parameter_settings(self):
      return initializer if initializer else \
      {
          self.weight : {'init_rule' : 'xavier'},
          self.bias   : {'init_rule' : 'constant'}
      }


class Dropout(Module):
    def __init__(self, p):
        super(Dropout, self).__init__()
        self.probability = p
    def forward(self, inputs, params):
        return layers.dropout(inputs, self.probability, params['__training_in_progress__'])
    def output_shape(self, input_shape):
        return input_shape
      

class Pooling(Module):
    count = 0
    def __init__(self, mode, kernel_shape, stride=(1, 1), pad=(0, 0)):
        '''
          mode: 'avg', 'max', 'sum'
        '''
        super(Pooling, self).__init__()
        self.kernel_shape  = kernel_shape
        self.mode          = mode
        self.stride        = stride
        self.pad           = pad

        self.__class__.count += 1

        self.inputs = mx.sym.Variable(name='inputs')
        self.pooling = mx.sym.Pooling(
            name       = 'pooling',
            data       = self.inputs,
            kernel     = self.kernel_shape,
            pool_type  = self.mode,
            stride     = self.stride,
            pad        = self.pad
        )

    def forward(self, inputs, params):
        args = {'inputs' : inputs}
        return minpy.core.Function(self.pooling, {'inputs':inputs.shape})(**args)

    def output_shape(self, input_shape):
        __, output_shape, __ = self.pooling.infer_shape(inputs=tuple([1] + list(input_shape)))
        return normal_shape(output_shape[0][1:])


class Identity(Module):
    def __init__(self):
        super(Identity, self).__init__()
    def forward(self, inputs, *args):
        return inputs
    def output_shape(self, input_shape):
        return input_shape


class Export(Identity):
    def __init__(self, label, storage):
        super(Export, self).__init__()
        assert label not in storage, 'duplicated label'
        self.label, self.storage = label, storage
        self.storage.update({self.label : None})
    def forward(self, inputs, params):
        # TODO policy train_only test_only default
        self.storage[self.label] = inputs
        return inputs


class ReLU(Module):
    def __init__(self):
        super(ReLU, self).__init__()
    def forward(self, inputs, *args):
        return layers.relu(inputs)
    def output_shape(self, input_shape):
        return input_shape
   

class Sigmoid(Module):
    def __init__(self):
        super(Sigmoid, self).__init__()
    def forward(self, inputs, *args):
        return 1 / (1 + np.exp(-inputs))
    def output_shape(self, input_shape):
        return input_shape


class Tanh(Module):
    def __init__(self):
        super(Tanh, self).__init__()
    def forward(self, inputs, *args):
        return np.tanh(inputs)
    def output_shape(self, input_shape):
        return input_shape


class Reshape(Module):
    def __init__(self, shape):
        '''
          shape: the new shape of one sample, e.g. (3072,) or (3, 32, 32)
        '''
        super(Reshape, self).__init__()
        self.shape = shape
    def forward(self, inputs, *args):
        shape = tuple([inputs.shape[0]] + list(self.shape))
        return np.reshape(inputs, shape)
    def output_shape(self, input_shape):
        return self.shape


class Flatten(Module):
    def __init__(self):
        super(Flatten, self).__init__()
    def forward(self, inputs, *args):
        shape = (inputs.shape[0], np.prod(np.array(inputs.shape[1:])))
        return np.reshape(self, shape)
    def output_shape(self, input_shape):
        return (np.prod(np.array(input_shape)),)


class Add(Module):
    def __init__(self, *args):
        '''
          args: the operations to be performed on inputs in parallel,
                the results are added elementwise
        '''
        assert all(isinstance(arg, Module) for arg in args)
        self.__modules = list(args)

    def forward(self, inputs, params):
        return sum(self.__modules[i].forward(inputs, params) \
            for i in range(len(self.__modules)))

    def output_shape(self, input_shape):
        shape = self.__modules[0].output_shape(input_shape)
        assert all(self.__modules[i].output_shape(input_shape) == shape \
            for i in range(1, len(self.__modules)))
        return shape

    def parameter_shape(self, input_shape):
        shapes = {}
        for module in self.__modules:
            shapes.update(module.parameter_shape(input_shape))
        return shapes


class Model(ModelBase):
    """ """
    def __init__(self, container, loss, input_shape):
        """
        :param Module container:
        :param str or callable loss: The loss function. Options: 'l2', 'softmax', 'svm' or customized functions receivingpredict and label as parameters.
        :param input_shape:
        """

        self.loss_function = loss
        super(Model, self).__init__()
        self.__container = container
        
        shapes = container.parameter_shape(input_shape)
        settings = container.parameter_settings()
        for key in shapes:
            if key not in settings:
                settings.update({key : {}})

        reduce(
            lambda arg, key : arg.add_param(name=key, shape=shapes[key], **settings[key]),
            shapes.keys(),
            self
        )

    def forward(self, X, mode):
        # TODO improve the method to distinguish training and test
        self.params.update({'__training_in_progress__' : mode})

        outputs = self.__container.forward(X, self.params)
        del self.params['__training_in_progress__']
        return outputs

    def loss(self, prediction, labels):
        if self.loss_function in ('l2', 'softmax', 'svm'):
            return getattr(layers, '%s_loss' % self.loss_function)(prediction, labels)
        else:
            return self.loss_function(prediction, labels)

# assistance functions
def normal_shape(shape):
    return tuple(int(d) for d in shape)


def swapaxes(inputs, axis0, axis1):
    data = mx.sym.Variable(name='inputs')
    swapped = mx.sym.SwapAxis(data=data, dim1=axis0, dim2=axis1)
    return minpy.core.Function(swapped, {'inputs':inputs.shape})(inputs=inputs)


def transpose(inputs, axes):
    data = mx.sym.Variable(name='inputs')
    transposed = mx.sym.transpose(data=data, axes=axes)
    return minpy.core.Function(transposed, {'inputs':inputs.shape})(inputs=inputs)
