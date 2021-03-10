"""
A few functions to help out with specific tasks
"""
import numpy as np
import pathlib

import h5py
from typing import Union, List, Tuple
import salvus.mesh.unstructured_mesh
import multi_mesh.components.salvus_mesh_reader as smr


def get_rot_matrix(angle, x, y, z):
    """
    :param angle: Rotation angle in radians (Right-Hand rule)
    :param x: x-component of rotational vector
    :param y: y-component of rotational vector
    :param z: z-component of rotational vector
    :return: Rotational Matrix
    """
    # Normalize vector.
    norm = np.sqrt(x ** 2 + y ** 2 + z ** 2)
    x /= norm
    y /= norm
    z /= norm

    # Setup matrix components.
    matrix = np.empty((3, 3))
    matrix[0, 0] = np.cos(angle) + (x ** 2) * (1 - np.cos(angle))
    matrix[1, 0] = z * np.sin(angle) + x * y * (1 - np.cos(angle))
    matrix[2, 0] = (-1) * y * np.sin(angle) + x * z * (1 - np.cos(angle))
    matrix[0, 1] = x * y * (1 - np.cos(angle)) - z * np.sin(angle)
    matrix[1, 1] = np.cos(angle) + (y ** 2) * (1 - np.cos(angle))
    matrix[2, 1] = x * np.sin(angle) + y * z * (1 - np.cos(angle))
    matrix[0, 2] = y * np.sin(angle) + x * z * (1 - np.cos(angle))
    matrix[1, 2] = (-1) * x * np.sin(angle) + y * z * (1 - np.cos(angle))
    matrix[2, 2] = np.cos(angle) + (z * z) * (1 - np.cos(angle))

    return matrix


def rotate(x, y, z, matrix):
    """
    :param x: x-coordinates to be rotated
    :param y: y-coordinates to be rotated
    :param z: z-coordinates to be rotated
    :param matrix: Rotational matrix obtained from get_rot_matrix
    :return: Rotated x,y,z coordinates
    """

    x, y, z = np.asarray(x), np.asarray(y), np.asarray(z)
    return matrix.dot(np.array([x, y, z]))


def rotate_mesh(mesh, event_loc, backwards=False):
    """
    Rotate the coordinates of a mesh to make the source show up below
    the North Pole of the mesh. Can also be used to rotate backwards.
    :param mesh: filename of mesh to be rotated
    :param event_loc: location of event to be rotated to N [lat, lon]
    :param backwards: Backrotation uses transpose of rot matrix
    """

    event_vec = [
        np.cos(event_loc[0]) * np.cos(event_loc[1]),
        np.cos(event_loc[0]) * np.sin(event_loc[1]),
        np.sin(event_loc[0]),
    ]
    event_vec = np.array(event_vec) / np.linalg.norm(event_vec)
    north_vec = np.array([0.0, 0.0, 1.0])

    rotate_axis = np.cross(event_vec, north_vec)
    rotate_axis /= np.linalg.norm(rotate_axis)
    # Make sure that both axis and angle make sense with r-hand-rule
    rot_angle = np.arccos(np.dot(event_vec, north_vec))
    rot_mat = get_rot_matrix(
        rot_angle, rotate_axis[0], rotate_axis[1], rotate_axis[2]
    )
    if backwards:
        rot_mat = rot_mat.T

    mesh = exodus(mesh, mode="a")
    points = mesh.get_coords()
    rotated_points = rotate(
        x=points[0], y=points[1], z=points[2], matrix=rot_mat
    )
    rotated_points = rotated_points.T

    mesh.put_coords(
        rotated_points[:, 0], rotated_points[:, 1], rotated_points[:, 2]
    )

    # It's not rotating in the right direction but that remains to be
    # configured properly.


def sph2cart(col, lon, rad):
    """
    Given spherical coordinates as input, returns their cartesian equivalent.
    :param col: Colatitude [radians].
    :param lon: Longitude [radians].
    :param rad: Radius.
    :return: x, y, z.
    """

    col, lon, rad = np.asarray(col), np.asarray(lon), np.asarray(rad)
    if (0 > col).any() or (col > np.math.pi).any():
        raise ValueError("Colatitude must be in range [0, pi].")

    x = rad * np.sin(col) * np.cos(lon)
    y = rad * np.sin(col) * np.sin(lon)
    z = rad * np.cos(col)

    return x, y, z


def cart2sph(x, y, z):
    """
    Given cartesian coordinates, returns their spherical equivalent.
    :param x: x.
    :param y: y.
    :param z: z.
    :return: colatitude, longitude, and radius
    """

    x, y, z = np.asarray(x), np.asarray(y), np.asarray(z)
    r = np.sqrt(x ** 2 + y ** 2 + z ** 2)

    # Handle division by zero at the core
    with np.errstate(invalid="ignore"):
        c = np.divide(z, r)
        c = np.nan_to_num(c)

    c = np.arccos(c)
    l = np.arctan2(y, x)
    return c, l, r


def remove_and_create_empty_dataset(
    gll_model, parameters: list, model: str, coordinates: str
):
    """
    Take gll dataset, delete it and create an empty one ready for the new
    set of parameters that are to be input to the mesh.
    """
    if model in gll_model:
        del gll_model[model]
    gll_model.create_dataset(
        name=model,
        shape=(
            gll_model[coordinates].shape[0],
            len(parameters),
            gll_model[coordinates].shape[1],
        ),
        dtype=np.float64,
    )

    create_dimension_labels(gll_model, parameters)


def create_dimension_labels(gll, parameters: list):
    """
    Create the dimstring which is needed in the h5 meshes.
    :param gll_model: The gll mesh which needs the new dimstring
    :param parameters: The parameters which should be in the dimstring
    """
    dimstr = "[ " + " | ".join(parameters) + " ]"
    gll["MODEL/data"].dims[0].label = "element"
    gll["MODEL/data"].dims[1].label = dimstr
    gll["MODEL/data"].dims[2].label = "point"


def pick_parameters(parameters):
    if parameters == "TTI":
        parameters = [
            "VPV",
            "VPH",
            "VSV",
            "VSH",
            "RHO",
            "ETA",
            "QKAPPA",
            "QMU",
        ]
    elif parameters == "ISO":
        parameters = ["QKAPPA", "QMU", "RHO", "VP", "VS"]
    else:
        parameters = parameters

    return parameters

def load_hdf5_params_to_memory(gll: str, model: str, coordinates: str):
    """
    Load coordinates, data and parameter list from and hdf5 file into memory
    """

    with h5py.File(gll, "r") as mesh:
        points = np.array(mesh[coordinates][:], dtype=np.float64)
        data = mesh[model][:]
        params = mesh[model].attrs.get("DIMENSION_LABELS")[1].decode()
        params = params[2:-2].replace(" ", "").replace("grad", "").split("|")

    return points, data, params


def _create_mask(
    mesh: salvus.mesh.unstructured_mesh.UnstructuredMesh,
    layers: List[int],
) -> np.ndarray:
    """
    Create an array which is used to mask elements in the dataset

    :param mesh: A salvus mesh
    :type mesh: salvus.mesh.unstructured_mesh.UnstructuredMesh
    :param layers: A list with the layers used in the interpolation
    :type layers: List[int]
    :return: An array with the indices of the used elements
    :rtype: np.ndarray
    """
    # We create a boolean array to represent the mask
    mask = {}
    for layer in layers:
        le_mask = np.zeros_like(mesh.elemental_fields["layer"], dtype=bool)
        mask[str(layer)] = np.logical_or(
            le_mask, mesh.elemental_fields["layer"] == layer
        )
    # mask = np.zeros_like(mesh.elemental_fields["layer"], dtype=bool)
    # for layer in layers:
    #     mask = np.logical_or(mask, mesh.elemental_fields["layer"] == layer)
    return mask, layers


def _assess_layers(
    mesh: Union[
        salvus.mesh.unstructured_mesh.UnstructuredMesh, smr.SalvusMesh
    ],
    layers: Union[List[int], str],
) -> Tuple[List[int], bool]:
    """
    Figure out which numerical layers are needed

    :param data: The data file already read with h5py
    :type data: salvus.mesh.unstructured_mesh.UnstructuredMesh
    :param layers: Description of layers used to mask mesh
    :type layers: Union[List[int], str]
    """
    # We sort layers in descending order in order to make moho_idx make sense
    _ = mesh.get_elemental_fields()
    mesh_layers = np.sort(np.unique(mesh.elemental_fields["layer"]))[
        ::-1
    ].astype(int)

    # If requested layers are a list, we just check validity of list and return
    if isinstance(layers, (list, np.ndarray)):
        if np.max(layers) > np.max(mesh_layers):
            raise ValueError("Requested layers not in mesh")
        if np.min(layers) < np.min(mesh_layers):
            raise ValueError("Requested layers not in mesh")
        if set(mesh_layers) == set(layers):
            mask = False
        else:
            mask = True
        return layers, mask
    if isinstance(layers, int):
        if layers not in mesh_layers:
            raise ValueError("Requested layer not in mesh")
        return [layers], True
    # Else, we have to figure stuff out
    available_layers = ["all", "crust", "mantle", "core", "nocore"]
    if not isinstance(layers, str):
        raise ValueError(
            f"Input for layers needs to be a list of one of: "
            f"{available_layers}"
        )
    # The layers are arranged outwards from the core
    moho_idx = int(mesh.global_strings["moho_idx"])
    mask = True
    if layers == "all":
        return mesh_layers, False
    elif layers == "crust":
        return mesh_layers[:moho_idx], mask
    else:
        o_core_idx = mesh.elemental_fields["layer"][
            np.where(mesh.elemental_fields["fluid"] == 1)[0][0]
        ]
        o_core_idx = np.where(mesh_layers == o_core_idx)[0][0]
        if layers == "mantle":
            return mesh_layers[moho_idx:o_core_idx], mask
        elif layers == "core":
            return mesh_layers[o_core_idx:], mask
        elif layers == "nocore":
            return mesh_layers[:o_core_idx], mask
        else:
            raise ValueError(
                f"Only allowed string layer inputs are: {available_layers}"
            )


def create_layer_mask(
    mesh: salvus.mesh.unstructured_mesh.UnstructuredMesh,
    layers: Union[List[int], "str"],
):
    """
    Create a masking array for the layers that need to be masked away from a mesh

    :param mesh: Mesh to mask elements away from
    :type mesh: salvus.mesh.unstructured_mesh.UnstructuredMesh
    :param layers: Layers to use
    :type layers: Union[List[int],
    """
    layers, i_should_mask = _assess_layers(mesh=mesh, layers=layers)
    return _create_mask(mesh=mesh, layers=layers)
    # layers, i_should_mask = _assess_layers(mesh=mesh, layers=layers)
    # if i_should_mask:
    #     mask = _create_mask(mesh=mesh, layers=layers)
    # else:
    #     mask = np.ones_like(mesh.elemental_fields["layer"], dtype=bool)
    # return mask


def get_unique_points(
    points: Union[
        np.array, str, salvus.mesh.unstructured_mesh.UnstructuredMesh
    ],
    mesh=False,
    layers=None,
):
    """
    Take an array of coordinates and find the unique coordinates. Returns
    the unique coordinates and an array of indices that can be used to
    reconstruct the previous array.

    :param points: Coordinates, or a file
    :type points: Union[numpy.array, str,
        salvus.mesh.unstructured_mesh.UnstructuredMesh]
    :param mesh: If you want to take points straight from a mesh,
        then points are a UnstructuredMesh object
    :type mesh: bool
    :param layers: If points are restricted to specific layers.
    :type layers: Union[List[int], str]
    """
    if isinstance(points, np.ndarray):
        all_points = points.reshape(
            (points.shape[0] * points.shape[1], points.shape[2])
        )
        return np.unique(all_points, return_inverse=True, axis=0)
    else:
        # First we deal with the input variables, especially the layers
        layers, _ = _assess_layers(mesh=points, layers=layers)
        # if i_should_mask:
        mask, _ = _create_mask(mesh=points, layers=layers)
        # else:
        #     mask = np.ones_like(points.elemental_fields["layer"], dtype=bool)
        # coords = points.get_element_nodes()
        # coords = coords.reshape(
        #     (coords.shape[0] * coords.shape[1], coords.shape[2])
        # )
        # r_mesh_1d = (
        #     points.element_nodal_fields["z_node_1D"][mask].ravel() * 6371000.0
        # )
        unique_points = {}
        for layer in layers:
            nodes = points.get_element_nodes()[mask[str(layer)]]
            unique_points[str(layer)] = np.unique(
                nodes.reshape(
                    (nodes.shape[0] * nodes.shape[1], nodes.shape[2])
                ),
                return_inverse=True,
                axis=0,
            )
        return (
            unique_points,
            mask,
            layers,
        )


def lat2colat(lat):
    return 90.0 - lat


def colat2lat(colat):
    return 90.0 - colat


def latlondepth_to_xyz(latlondepth: np.array):
    """
    Coordinate transformation from lat lon depth to x y z.
    :param latlondepth: [description]
    :type latlondepth: np.array
    :param xyz: [description]
    :type xyz: np.array
    """
    r_earth = 6371000.0
    r = r_earth - latlondepth[:, 2]
    colat = lat2colat(latlondepth[:, 0])
    colat, lon = map(np.deg2rad, [colat, latlondepth[:, 1]])
    x = r * np.sin(colat) * np.cos(lon)
    y = r * np.sin(colat) * np.sin(lon)
    z = r * np.cos(colat)
    xyz = np.array([x, y, z]).T
    return xyz


def sph2cart(col, lon, rad):
    """
    Given spherical coordinates as input, returns their cartesian equivalent.
    :param col: Colatitude [radians].
    :param lon: Longitude [radians].
    :param rad: Radius.
    :return: x, y, z.
    """

    col, lon, rad = np.asarray(col), np.asarray(lon), np.asarray(rad)
    if (0 > col).any() or (col > np.math.pi).any():
        raise ValueError("Colatitude must be in range [0, pi].")

    x = rad * np.sin(col) * np.cos(lon)
    y = rad * np.sin(col) * np.sin(lon)
    z = rad * np.cos(col)

    return x, y, z


def cart2sph(x, y, z):
    """
    Given cartesian coordinates, returns their spherical equivalent.
    :param x: x.
    :param y: y.
    :param z: z.
    :return: colatitude, longitude, and radius
    """

    x, y, z = np.asarray(x), np.asarray(y), np.asarray(z)
    r = np.sqrt(x ** 2 + y ** 2 + z ** 2)

    # Handle division by zero at the core
    with np.errstate(invalid="ignore"):
        c = np.divide(z, r)
        c = np.nan_to_num(c)

    c = np.arccos(c)
    l = np.arctan2(y, x)
    return c, l, r
