import numpy as np
import itertools
import copy
from collections import namedtuple, Iterable

try:
    from itaps import iMesh, iBase, iMeshExtensions
except ImportError:
    raise ImportError("The mesh module requires imports of iMesh, iBase, and"
          " iMeshExtensions from PyTAPS")

from pyne.material import Material, MaterialLibrary

# dictionary of lamba functions for mesh arithmetic
_ops = {"+": lambda val_1, val_2: (val_1 + val_2), 
        "-": lambda val_1, val_2: (val_1 - val_2),
        "*": lambda val_1, val_2: (val_1 * val_2),
        "/": lambda val_1, val_2: (val_1 / val_2)}

err__ops = {"+": lambda val_1, val_2, val_1_err, val_2_err: \
                 (1/(val_1 + val_2)*np.sqrt((val_1*val_1_err)**2 \
                  + (val_2*val_2_err)**2)), 
            "-": lambda val_1, val_2, val_1_err, val_2_err: \
                 (1/(val_1 - val_2)*np.sqrt((val_1*val_1_err)**2 \
                 + (val_2*val_2_err)**2)),
            "*": lambda val_1, val_2, val_1_err, val_2_err: \
                 (np.sqrt(val_1_err**2 + val_2_err**2)),
                  "/": lambda val_1, val_2, val_1_err, val_2_err: \
                 (np.sqrt(val_1_err**2 + val_2_err**2))}

class MeshError(Exception):
    """Errors related to instantiating mesh objects and utilizing their methods.
    """
    pass

class Mesh(object):        
    """This class houses any iMesh instance and contains methods for various mesh
    operations. Special methods exploit the properties of structured mesh.

    Atrributes
    ----------
    mesh : iMesh instance
    mesh_file : string
        File name of file containing iMesh instance.
    structured : bool
        True for structured mesh.
    structured_coords : list of lists
        A list containing lists of x_points, y_points and z_points that make up
        a structured mesh. 
    structured_set : iMesh entity set handle
        A preexisting structured entity set on an iMesh instance with a
        "BOX_DIMS" tag.

        Unstructured mesh instantiation:
             - From iMesh instance by specifying: <mesh>
             - From mesh file by specifying: <mesh_file>

        Structured mesh instantiation:
            - From iMesh instance with exactly 1 entity set (with BOX_DIMS tag)
              by specifying <mesh> and structured = True.
            - From mesh file with exactly 1 entity set (with BOX_DIMS tag) by
              specifying <mesh_file> and structured = True.
            - From an imesh instance with multiple entity sets by specifying 
              <mesh>, <structured_set>, structured=True.
            - From coordinates by specifying <structured_coords>,
              structured=True, and optional preexisting iMesh instance <mesh>

        The "BOX_DIMS" tag on iMesh instances containing structured mesh is
        a vector of floats it the following form:
        [i_min, j_min, k_min, i_max, j_max, k_max]
        where each value is a volume element index number. Typically volume 
        elements should be indexed from 0. The "BOX_DIMS" information is stored
        in self.dims.
    mats : MaterialLibrary or dict or Materials or None
        This is a mapping of volume element handles to Material objects.

    """

    def __init__(self, mesh=None, mesh_file=None, structured=False, \
                 structured_coords=None, structured_set=None, mats=None):
        if mesh:
            self.mesh = mesh
        else: 
            self.mesh = iMesh.Mesh()

        self.structured = structured

        #Unstructured mesh cases
        if not self.structured:
            #Error if structured arguments are passed
            if structured_coords or structured_set:
                MeshError("Structured mesh arguments should not be present for\
                            unstructured Mesh instantiation.")

            #From imesh instance
            if mesh and not mesh_file:
                pass
            #From file
            elif mesh_file and not mesh:
                self.mesh.load(mesh_file)
                self.mats = MaterialLibrary(mesh_file)
            else:
                raise MeshError("To instantiate unstructured mesh object, "
                                 "must supply exactly 1 of the following: "
                                 "<mesh>, <mesh_file>.")

        #structured mesh cases
        elif self.structured:
            #From mesh or mesh_file
            if (mesh or mesh_file) and not structured_coords \
                                   and not structured_set:
                if mesh_file:
                    self.mesh.load(mesh_file)
                    self.mats = MaterialLibrary(mesh_file)
                try:
                    self.mesh.getTagHandle("BOX_DIMS")
                except iBase.TagNotFoundError as e:
                    print "BOX_DIMS not found on iMesh instance"
                    raise e

                count = 0
                for ent_set in self.mesh.rootSet.getEntSets():
                    try:
                        self.mesh.getTagHandle("BOX_DIMS")[ent_set]
                    except iBase.TagNotFoundError:
                        pass
                    else:
                        self.structured_set = ent_set
                        count += 1

                if count == 0:
                    raise MeshError("Found no structured meshes in "
                                    "file {0}".format(mesh_file))
                elif count > 1:
                    raise MeshError("Found {0} structured meshes."
                                    " Instantiate individually using"
                                    " from_ent_set()".format(count))
            # from coordinates                       
            elif not mesh and not mesh_file and structured_coords \
                                            and not structured_set:
                extents = [0, 0, 0] + [len(x) - 1 for x in structured_coords]
                self.structured_set = self.mesh.createStructuredMesh(
                     extents, i=structured_coords[0], j=structured_coords[1], 
                     k=structured_coords[2], create_set=True)

            #From mesh and structured_set:
            elif mesh and not mesh_file and not structured_coords \
                                        and structured_set:
                try:
                    self.mesh.getTagHandle("BOX_DIMS")[structured_set]
                except iBase.TagNotFoundError as e:
                    print("Supplied entity set does not contain BOX_DIMS tag")
                    raise e

                self.structured_set = structured_set
            else:
                raise MeshError("For structured mesh instantiation, need to"
                                "supply exactly one of the following:\n"
                                "A. iMesh instance\n"
                                "B. Mesh file\n"
                                "C. Mesh coordinates\n"
                                "D. Structured entity set AND iMesh instance")

            self.dims = self.mesh.getTagHandle("BOX_DIMS")[self.structured_set]
            self.vertex_dims = list(self.dims[0:3]) \
                               + [x + 1 for x in self.dims[3:6]]
        # sets mats
        if mats is None:
            mats = MaterialLibrary()
        elif not isinstance(mats, MaterialLibrary):
            mats = MaterialLibrary(mats)
        self.mats = mats

        # tag with volume id and ensure mats exist.
        tags = self.mesh.getAllTags(list(self.mesh.iterate(iBase.Type.region, 
                                                           iMesh.Topology.all))[0])
        tags = set(tag.name for tag in tags)
        if 've_idx' in tags:
            tag_ve_idx = self.mesh.getTagHandle('ve_idx')
        else:
            tag_ve_idx = self.mesh.createTag('ve_idx', 1, int)
        for i, ve in enumerate(self.mesh.iterate(iBase.Type.region, 
                                                 iMesh.Topology.all)):
            tag_ve_idx[ve] = i
            if i not in mats:
                mats[i] = Material()

#    def __add__(self, other):
#        """Adds the common tags of other and returns a new mesh object.
#        """
#        tags = self.common_ve_tags(other)
#        return self._do_op(other, tags, "+", in_place=False)
#
#    def __sub__(self, other):
#        """Subtracts the common tags of other and returns a new mesh object.
#        """
#        tags = self.common_ve_tags(other)
#        return self._do_op(other, tags, "-", in_place=False)
#
#    def __mul__(self, other):
#        """Multiplies the common tags of other and returns a new mesh object.
#        """
#        tags = self.common_ve_tags(other)
#        return  self._do_op(other, tags, "*", in_place=False)
#
#    def __div__(self, other):
#        """Adds the common tags of other and returns a new mesh object.
#        """
#        tags = self.common_ve_tags(other)
#        return self._do_op(other, tags, "/", in_place=False)


    def add(self, other):
        """Adds the common tags of other to the mesh object.
        """
        tags = self.common_ve_tags(other)
        self._do_op(other, tags, "+")

    def sub(self, other):
        """Substracts the common tags of other to the mesh object.
        """
        tags = self.common_ve_tags(other)
        self._do_op(other, tags, "-")

    def mul(self, other):
        """Multiplies the common tags of other to the mesh object.
        """
        tags = self.common_ve_tags(other)
        self._do_op(other, tags, "*")

    def div(self, other):
        """Divides the common tags of other to the mesh object.
        """
        tags = self.common_ve_tags(other)
        self._do_op(other, tags, "/")

    def _do_op(self, other, tags, op, in_place=True):
        """Private function to do mesh +, -, *, /.
        """
        # Exclude error tags in a case a StatMesh is mistakenly initialized as a
        # Mesh object.
        tags = set(tag for tag in tags if not tag.endswith('_error'))

        if in_place:
            mesh_1 = self
        else:
            mesh_1 = copy.copy(self)

        for tag in tags:
            for ve_1, ve_2 in \
                zip(zip(iter(mesh_1.mesh.iterate(iBase.Type.region, iMesh.Topology.all))),
                    zip(iter(other.mesh.iterate(iBase.Type.region, iMesh.Topology.all)))):
                self.mesh.getTagHandle(tag)[ve_1] = \
                    _ops[op](mesh_1.mesh.getTagHandle(tag)[ve_1], 
                            other.mesh.getTagHandle(tag)[ve_2])

        return mesh_1


    def common_ve_tags(self, other):
        """Returns the volume element tags in common between self and other.
        """
        self_tags = self.mesh.getAllTags(list(self.mesh.iterate(
                                     iBase.Type.region, iMesh.Topology.all))[0])
        other_tags = other.mesh.getAllTags(list(other.mesh.iterate(iBase.Type.region, 
                                           iMesh.Topology.all))[0])
        self_tags = set(x.name for x in self_tags)
        other_tags = set(x.name for x in other_tags)
        intersect = self_tags & other_tags
        intersect.discard('ve_idx')
        return intersect
                           
    def __copy__(self):
        #first copy full imesh instance
        imesh_copy = iMesh.Mesh()

        #now create Mesh objected from copied iMesh instance
        mesh_copy = Mesh(mesh=imesh_copy, structured=copy.copy(self.structured))
        return mesh_copy

    #Structured methods:
    def structured_get_vertex(self, i, j, k):
        """Return the handle for (i,j,k)'th vertex in the mesh"""
        self._structured_check()
        n = _structured_find_idx(self.vertex_dims, (i, j, k))
        return _structured_step_iter(
            self.structured_set.iterate(iBase.Type.vertex, 
                                        iMesh.Topology.point), n)


    def structured_get_hex(self, i, j, k):
        """Return the handle for the (i,j,k)'th hexahedron in the mesh"""
        self._structured_check()
        n = _structured_find_idx(self.dims, (i, j, k))
        return _structured_step_iter(
            self.structured_set.iterate(iBase.Type.region, 
                                 iMesh.Topology.hexahedron), n)


    def structured_get_hex_volume(self, i, j, k):
        self._structured_check()
        """Return the volume of the (i,j,k)'th hexahedron in the mesh"""
        v = list(self.structured_iterate_vertex(x=[i, i + 1],
                                 y=[j, j + 1],
                                 z=[k, k + 1]))
        coord = self.mesh.getVtxCoords(v)
        dx = coord[1][0] - coord[0][0]
        dy = coord[2][1] - coord[0][1]
        dz = coord[4][2] - coord[0][2]
        return dx * dy * dz


    def structured_iterate_hex(self, order="zyx", **kw):
        """Get an iterator over the hexahedra of the mesh

        The order argument specifies the iteration order.  It must be a string
        of 1-3 letters from the set (x,y,z).  The rightmost letter is the axis
        along which the iteration will advance the most quickly.  Thus "zyx" --
        x coordinates changing fastest, z coordinates changing least fast-- is
        the default, and is identical to the order that would be given by the
        structured_set.iterate() function.

        When a dimension is absent from the order, iteration will proceed over
        only the column in the mesh that has the lowest corresonding (i/j/k)
        coordinate.  Thus, with order "xy," iteration proceeds over the i/j
        plane of the structured mesh with the smallest k coordinate.

        Specific slices can be specified with keyword arguments:

        Keyword args::

          x: specify one or more i-coordinates to iterate over.
          y: specify one or more j-coordinates to iterate over.
          z: specify one or more k-coordinates to iterate over.

        Examples::

          structured_iterate_hex(): equivalent to iMesh iterator over hexes in mesh
          structured_iterate_hex("xyz"): iterate over entire mesh, with k-coordinates
                                         changing fastest, i-coordinates least fast.
          structured_iterate_hex("yz", x=3): Iterate over the j-k plane of the mesh
                                             whose i-coordinate is 3, with k values
                                             changing fastest.
          structured_iterate_hex("z"): Iterate over k-coordinates, with i=dims.imin
                             and j=dims.jmin
          structured_iterate_hex("yxz", y=(3,4)): Iterate over all hexes with
                                        j-coordinate = 3 or 4.  k-coordinate
                                        values change fastest, j-values least
                                        fast.
        """
        self._structured_check()

        # special case: zyx order is the standard pytaps iteration order,
        # so we can save time by simply returning a pytaps iterator
        # if no kwargs were specified
        if order == "zyx" and not kw:
            return self.structured_set.iterate(iBase.Type.region,
                                       iMesh.Topology.hexahedron)

        indices, ordmap = _structured_iter_setup(self.dims, order, **kw)
        return _structured_iter(indices, ordmap, self.dims, 
            self.structured_set.iterate(iBase.Type.region, 
                                        iMesh.Topology.hexahedron))


    def structured_iterate_vertex(self, order="zyx", **kw):
        """Get an iterator over the vertices of the mesh

        See structured_iterate_hex() for an explanation of the order argument and the
        available keyword arguments.
        """
        self._structured_check()
        #special case: zyx order without kw is equivalent to pytaps iterator
        if order == "zyx" and not kw:
            return self.structured_set.iterate(iBase.Type.vertex,
                                               iMesh.Topology.point)

        indices, ordmap = _structured_iter_setup(self.vertex_dims, order, **kw)
        return _structured_iter(indices, ordmap, self.vertex_dims, 
                self.structured_set.iterate(iBase.Type.vertex, 
                                            iMesh.Topology.point))


    def structured_iterate_hex_volumes(self, order="zyx", **kw):
        """Get an iterator over the volumes of the mesh hexahedra

        See structured_iterate_hex() for an explanation of the order argument and the
        available keyword arguments.
        """
        self._structured_check()
        indices, _ = _structured_iter_setup(self.dims, order, **kw)
        # Use an inefficient but simple approach: call structured_get_hex_volume()
        # on each required i,j,k pair.  
        # A better implementation would only make one call to getVtxCoords.
        for A in itertools.product(*indices):
            # the ordmap returned from _structured_iter_setup maps to kji/zyx ordering,
            # but we want ijk/xyz ordering, so create the ordmap differently.
            ordmap = [order.find(L) for L in "xyz"]
            ijk = [A[ordmap[x]] for x in range(3)]
            yield self.structured_get_hex_volume(*ijk)


    def structured_get_divisions(self, dim):
        """Get the mesh divisions on a given dimension

        Given a dimension "x", "y", or "z", return a list of the mesh vertices
        along that dimension.
        """
        self._structured_check()
        if len(dim) == 1 and dim in "xyz":
            idx = "xyz".find(dim)
            return [self.mesh.getVtxCoords(i)[idx]
                    for i in self.structured_iterate_vertex(dim)]
        else:
            raise MeshError("Invalid dimension: {0}".format(str(dim)))

    def _structured_check(self):
        if not self.structured:
            raise MeshError("Structured mesh methods cannot be called from "\
                            "unstructured mesh instances.")

    def write_hdf5(self, filename):
        """Writes the mesh to an hdf5 file."""
        self.mesh.save(filename)
        self.mats.write_hdf5(filename)

######################################################
# private helper functions for structured mesh methods
######################################################

def _structured_find_idx(dims, ijk):
    """Helper method fo structured_get_vertex and structured_get_hex.

    For tuple (i,j,k), return the number N in the appropriate iterator.
    """
    dim0 = [0] * 3
    for i in xrange(0, 3):
        if (dims[i] > ijk[i] or dims[i + 3] <= ijk[i]):
            raise MeshError(str(ijk) + " is out of bounds")
        dim0[i] = ijk[i] - dims[i]
    i0, j0, k0 = dim0
    n = (((dims[4] - dims[1]) * (dims[3] - dims[0]) * k0) +
         ((dims[3] - dims[0]) * j0) +
         i0)
    return n


def _structured_step_iter(it, n):
    """Helper method for structured_get_vertex and structured_get_hex

    Return the nth item in the iterator."""
    it.step(n)
    r = it.next()
    it.reset()
    return r


def _structured_iter_setup(dims, order, **kw):
    """Setup helper function for StrMesh iterator functions

    Given dims and the arguments to the iterator function, return
    a list of three lists, each being a set of desired coordinates,
    with fastest-changing coordinate in the last column),
    and the ordmap used by _structured_iter to reorder each coodinate to (i,j,k).
    """
    # a valid order has the letters "x", "y", and "z"
    # in any order without duplicates
    if not (len(order) <= 3 and
            len(set(order)) == len(order) and
            all([a in "xyz" for a in order])):
        raise MeshError("Invalid iteration order: " + str(order))

    # process kw for validity
    spec = {}
    for idx, d in enumerate("xyz"):
        if d in kw:
            spec[d] = kw[d]
            if not isinstance(spec[d], Iterable):
                spec[d] = [spec[d]]
            if not all(x in range(dims[idx], dims[idx + 3])
                    for x in spec[d]):
                raise MeshError( \
                        "Invalid iterator kwarg: {0}={1}".format(d, spec[d]))
            if d not in order and len(spec[d]) > 1:
                raise MeshError("Cannot iterate over" + str(spec[d]) +
                                   "without a proper iteration order")
        if d not in order:
            order = d + order
            spec[d] = spec.get(d, [dims[idx]])

    # get indices and ordmap
    indices = []
    for L in order:
        idx = "xyz".find(L)
        indices.append(spec.get(L, xrange(dims[idx], dims[idx + 3])))

    ordmap = ["zyx".find(L) for L in order]
    return indices, ordmap


def _structured_iter(indices, ordmap, dims, it):
    """Iterate over the indices lists, yielding _structured_step_iter(it) for each.
    """
    d = [0, 0, 1]
    d[1] = (dims[3] - dims[0])
    d[0] = (dims[4] - dims[1]) * d[1]
    mins = [dims[2], dims[1], dims[0]]
    offsets = ([(a - mins[ordmap[x]]) * d[ordmap[x]]
                for a in indices[x]]
                for x in range(3))
    for ioff, joff, koff in itertools.product(*offsets):
        yield _structured_step_iter(it, (ioff + joff + koff))


class StatMesh(Mesh):
    def __init__(self, mesh=None, mesh_file=None, structured=False,
                 structured_coords=None, structured_set=None):

        super(StatMesh, self).__init__(mesh=mesh, mesh_file=mesh_file, 
              structured=structured, structured_coords=structured_coords, 
              structured_set=structured_set)

    def _do_op(self, other, tags, op, in_place=True):
        """Private function to do mesh +, -, *, /. Called by operater overloading
        functions.
        """
        # Exclude error tags because result and error tags are treated simotaneously
        # so there is not need to include both in the tag list to iterate through.
        tags = set(tag for tag in tags if not tag.endswith('_error'))

        if in_place:
            mesh_1 = self
        else:
            mesh_1 = copy.copy(self)

        for tag in tags:
            for ve_1, ve_2 in \
                zip(zip(iter(mesh_1.mesh.iterate(iBase.Type.region, iMesh.Topology.all))),
                    zip(iter(other.mesh.iterate(iBase.Type.region, iMesh.Topology.all)))):

                mesh_1.mesh.getTagHandle(tag + "_error")[ve_1] = err__ops[op](
                    mesh_1.mesh.getTagHandle(tag)[ve_1], 
                    other.mesh.getTagHandle(tag)[ve_2], 
                    mesh_1.mesh.getTagHandle(tag + "_error")[ve_1], 
                    other.mesh.getTagHandle(tag + "_error")[ve_2])

                mesh_1.mesh.getTagHandle(tag)[ve_1] = \
                    _ops[op](mesh_1.mesh.getTagHandle(tag)[ve_1], 
                            other.mesh.getTagHandle(tag)[ve_2])

        return mesh_1
